"""Opt-in x64 native plugin loading for a freshly launched Victoria 3 process.

Uses Windows LoadLibraryW and a dedicated remote thread for the plugin's
V3NL_PluginInit export. Never creates the game suspended, patches its EXE,
injects into an existing user process, or changes other processes.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
import time

from .plugins import NativePlugin

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS = 0x4
GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT = 0x2


class RemoteInjectionError(RuntimeError):
    pass


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


def _api():
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RemoteInjectionError("The native loader requires 64-bit Windows.")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], ctypes.c_void_p),
        "CloseHandle": ([ctypes.c_void_p], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], ctypes.c_void_p),
        "Module32FirstW": ([ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)], wintypes.BOOL),
        "Module32NextW": ([ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)], wintypes.BOOL),
        "VirtualAllocEx": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD], ctypes.c_void_p),
        "VirtualFreeEx": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD], wintypes.BOOL),
        "WriteProcessMemory": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "CreateRemoteThread": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], ctypes.c_void_p),
        "WaitForSingleObject": ([ctypes.c_void_p, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeThread": ([ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "GetModuleHandleW": ([wintypes.LPCWSTR], ctypes.c_void_p),
        "GetModuleHandleExW": ([wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)], wintypes.BOOL),
        "GetModuleFileNameW": ([ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD),
        "GetProcAddress": ([ctypes.c_void_p, ctypes.c_char_p], ctypes.c_void_p),
    }
    for name, (params, result) in signatures.items():
        f = getattr(k, name)
        f.argtypes, f.restype = params, result
    return k


def _error(msg: str) -> RemoteInjectionError:
    return RemoteInjectionError(f"{msg} (Win32 error {ctypes.get_last_error()})")


def _remote_modules(k, pid: int) -> dict[str, tuple[int, str]]:
    for attempt in range(8):
        shot = k.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if shot and shot != ctypes.c_void_p(-1).value:
            try:
                result: dict[str, tuple[int, str]] = {}
                entry = MODULEENTRY32W()
                entry.dwSize = ctypes.sizeof(entry)
                if not k.Module32FirstW(shot, ctypes.byref(entry)):
                    raise _error("Cannot enumerate target modules")
                while True:
                    result[entry.szModule.casefold()] = (int(entry.modBaseAddr), entry.szExePath)
                    if not k.Module32NextW(shot, ctypes.byref(entry)):
                        break
                return result
            finally:
                k.CloseHandle(shot)
        time.sleep(0.15)
    raise _error("Unable to obtain target module snapshot")


def _export_rva(dll: Path, export: str) -> int:
    import pefile
    pe = pefile.PE(str(dll), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
    for symbol in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
        if symbol.name == export.encode("ascii"):
            # Native plugins may not forward V3NL_PluginInit to a different DLL.
            if symbol.forwarder:
                raise RemoteInjectionError(f"Forwarded entry export is not supported: {dll}")
            return int(symbol.address)
    raise RemoteInjectionError(f"Entry export {export} not found in {dll}")


def _remote_loadlibrary(k, pid: int, handle: int) -> int:
    local_kernel = k.GetModuleHandleW("kernel32.dll")
    if not local_kernel:
        raise _error("Local kernel32.dll unavailable")
    function = k.GetProcAddress(local_kernel, b"LoadLibraryW")
    if not function:
        raise _error("LoadLibraryW unavailable")
    owner_base = ctypes.c_void_p()
    flags = GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT
    if not k.GetModuleHandleExW(flags, function, ctypes.byref(owner_base)):
        raise _error("Could not locate the actual module containing LoadLibraryW")
    buf = ctypes.create_unicode_buffer(32768)
    if not k.GetModuleFileNameW(owner_base, buf, len(buf)):
        raise _error("Cannot identify owner module for LoadLibraryW")
    owner_name = Path(buf.value).name.casefold()
    modules = _remote_modules(k, pid)
    if owner_name not in modules:
        raise RemoteInjectionError(f"{owner_name} is not loaded in the target process")
    local_offset = int(function) - int(owner_base.value)
    return modules[owner_name][0] + local_offset


def _run_thread(k, proc_handle: int, start: int, argument: int,
                timeout_ms: int, label: str) -> int:
    tid = wintypes.DWORD()
    thread = k.CreateRemoteThread(proc_handle, None, 0, ctypes.c_void_p(start),
                                  ctypes.c_void_p(argument), 0, ctypes.byref(tid))
    if not thread:
        raise _error(f"Cannot start native thread for {label}")
    try:
        result = k.WaitForSingleObject(thread, timeout_ms)
        if result == WAIT_TIMEOUT:
            # Caller must not free remote argument memory while thread is still using it.
            raise RemoteInjectionError(f"{label} did not finish within {timeout_ms} ms")
        if result != WAIT_OBJECT_0:
            raise _error(f"Failed waiting for {label}")
        code = wintypes.DWORD()
        if not k.GetExitCodeThread(thread, ctypes.byref(code)):
            raise _error(f"Failed querying {label} result")
        return int(code.value)
    finally:
        k.CloseHandle(thread)


def _verify_owned_process(pid: int, created: float, exe: Path) -> None:
    import psutil
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - created) > 2 or p.name().casefold() != "victoria3.exe":
            raise RemoteInjectionError("Game process identity changed; injection rejected")
        if Path(p.exe()).resolve() != exe.resolve():
            raise RemoteInjectionError("Game process path differs from the launched executable")
        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
            raise RemoteInjectionError("Game process has exited")
    except psutil.NoSuchProcess as ex:
        raise RemoteInjectionError("Game process no longer exists") from ex


def inject_plugin(pid: int, created: float, exe: Path,
                  plugin: NativePlugin, game_sha256: str) -> dict:
    """Load one validated DLL, then invoke DWORD WINAPI V3NL_PluginInit(void*).

    This API may run untrusted native code inside the game. UI requires opt-in.
    No OS-level suspension is performed.
    """
    _verify_owned_process(pid, created, exe)
    plugin.validate(game_sha256)
    k = _api()
    flags = (PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
             PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ)
    handle = k.OpenProcess(flags, False, pid)
    if not handle:
        raise _error(f"Unable to open owned game PID {pid}")
    remote_arg = None
    safe_free = False
    try:
        modules = _remote_modules(k, pid)
        dll = plugin.dll.resolve()
        name = dll.name.casefold()
        if name in modules:
            raise RemoteInjectionError(f"Native module {dll.name} is already loaded; refusing duplicate init")
        full = str(dll).encode("utf-16-le") + b"\0\0"
        remote_arg = k.VirtualAllocEx(handle, None, len(full),
                                      MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote_arg:
            raise _error("VirtualAllocEx failed")
        safe_free = True
        written = ctypes.c_size_t()
        source = ctypes.create_string_buffer(full)
        if not k.WriteProcessMemory(handle, remote_arg, source, len(full), ctypes.byref(written)):
            raise _error("Cannot write DLL path into owned game process")
        if written.value != len(full):
            raise RemoteInjectionError("Incomplete remote DLL path write")

        remote_load = _remote_loadlibrary(k, pid, handle)
        try:
            load_code = _run_thread(k, handle, remote_load, remote_arg, 30000, "LoadLibraryW")
        except RemoteInjectionError as ex:
            if "did not finish" in str(ex):
                safe_free = False
            raise
        # HMODULE returned through thread exit code is truncated on x64.
        # The real 64-bit module base is recovered from target's module list.
        target_base = None
        for attempt in range(12):
            matches = _remote_modules(k, pid)
            module = matches.get(name)
            if module and Path(module[1]).resolve() == dll:
                target_base = module[0]
                break
            time.sleep(0.1)
        if target_base is None:
            raise RemoteInjectionError(f"LoadLibraryW did not load expected plugin DLL: {dll}")
        export_rva = _export_rva(dll, plugin.init_export)
        _verify_owned_process(pid, created, exe)
        init_result = _run_thread(k, handle, target_base + export_rva, 0, 30000,
                                  plugin.init_export)
        if init_result:
            raise RemoteInjectionError(f"{plugin.id} init reported code {init_result}")
        return {"plugin_id": plugin.id, "dll": str(dll), "module_base": hex(target_base),
                "init_rva": hex(export_rva), "init_return_code": init_result,
                "game_pid": pid, "loaded": True}
    finally:
        if remote_arg is not None and safe_free:
            k.VirtualFreeEx(handle, remote_arg, 0, MEM_RELEASE)
        k.CloseHandle(handle)

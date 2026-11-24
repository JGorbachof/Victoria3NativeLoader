"""Manually invoked Win32 loader smoke against a disposable Python child, NEVER Victoria 3."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time
import os

from v3nl.win_inject import (
    _api, _remote_modules, _remote_loadlibrary, _run_thread,
    PROCESS_CREATE_THREAD, PROCESS_QUERY_INFORMATION, PROCESS_VM_OPERATION,
    PROCESS_VM_WRITE, PROCESS_VM_READ,
    MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, PAGE_READWRITE,
)


def main():
    if sys.platform != "win32":
        raise RuntimeError("Windows-only smoke test.")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(22)"],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        k = _api()
        handle = k.OpenProcess(
            PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
            PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ,
            False, child.pid)
        if not handle:
            raise RuntimeError(f"OpenProcess failed: {ctypes.get_last_error()}")
        allocation = None
        try:
            for i in range(15):
                try:
                    module_names = _remote_modules(k, child.pid)
                    break
                except Exception:
                    time.sleep(.2)
            else:
                raise RuntimeError("Cannot find child process system modules.")
            print("CHILD_SYSTEM_MODULES",len(module_names))
            source = str(Path(os.environ["SystemRoot"]) / "System32" / "version.dll")
            value = source.encode("utf-16-le") + b"\x00\x00"
            allocation = k.VirtualAllocEx(handle, None, len(value),
                                          MEM_COMMIT | MEM_RESERVE,PAGE_READWRITE)
            if not allocation:
                raise RuntimeError("VirtualAllocEx failed")
            count = ctypes.c_size_t()
            arr = ctypes.create_string_buffer(value)
            if not k.WriteProcessMemory(handle, allocation, arr, len(value), ctypes.byref(count)):
                raise RuntimeError("WriteProcessMemory failed")
            if count.value != len(value):
                raise RuntimeError("Incomplete WriteProcessMemory")
            load = _remote_loadlibrary(k, child.pid, handle)
            print("REMOTE_LOADLIBRARY",hex(load))
            code = _run_thread(k, handle, load, allocation, 12000, "system version.dll")
            print("REMOTE_THREAD_EXIT_LOW32",hex(code))
            modules_after = _remote_modules(k, child.pid)
            if "version.dll" not in modules_after:
                raise RuntimeError("Benign system DLL not found after LoadLibrary.")
            print("PASS_SYSTEM_DLL_LOADED_IN_DISPOSABLE_PROCESS",
                  modules_after["version.dll"][1])
        finally:
            if allocation:
                k.VirtualFreeEx(handle, allocation, 0, MEM_RELEASE)
            k.CloseHandle(handle)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=6)


if __name__ == "__main__":
    main()

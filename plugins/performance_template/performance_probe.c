/* Developer starter: NO-OP, not an optimization. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "../../sdk/v3_native_plugin.h"
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
DWORD WINAPI V3NL_PluginInit(LPVOID reserved)
{
    (void)reserved;
    if (!GetModuleHandleW(L"victoria3.exe")) return ERROR_MOD_NOT_FOUND;
    /* Actual hooks need verified signatures, no OS thread suspension,
       and preservation of original calculation semantics. */
    OutputDebugStringW(L"[V3NL perf template] No-op plugin ready.\n");
    return ERROR_SUCCESS;
}

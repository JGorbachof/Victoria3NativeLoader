#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "../../sdk/v3_native_plugin.h"

/* Deliberately does not modify or hook the game. Replace only after
 * verifying the precise game executable and native instruction signatures.
 * This DLL exists to verify plugin loading and ABI mechanics.
 */
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void) reserved;
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(instance);
    return TRUE;
}

DWORD WINAPI V3NL_PluginInit(LPVOID reserved)
{
    (void) reserved;
    OutputDebugStringW(L"[V3NL example] Native plugin initialized.\n");
    return ERROR_SUCCESS;
}

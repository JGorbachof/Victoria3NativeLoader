/* Victoria 3 Native Loader plugin ABI v1.
 * Plugin is loaded by LoadLibraryW in the ORIGINAL game process.
 * Native loader calls V3NL_PluginInit in its own remote thread.
 * This is a private, unstable game-hook ABI; compatible hashes are mandatory.
 * No game memory layout or Paradox internal API is guaranteed by this header.
 */
#ifndef V3NL_PLUGIN_H
#define V3NL_PLUGIN_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define V3NL_ABI_VERSION 1

#ifdef __cplusplus
extern "C" {
#endif

/* Returns ERROR_SUCCESS (0) when ready. Any nonzero code marks failure.
 * Called on a dedicated thread after LoadLibraryW succeeds.
 * Keep DllMain minimal; initialize callbacks/hooks in this function instead.
 * Do not block indefinitely; the loader waits at most 30 seconds.
 */
__declspec(dllexport) DWORD WINAPI V3NL_PluginInit(LPVOID reserved);

#ifdef __cplusplus
}
#endif

#endif

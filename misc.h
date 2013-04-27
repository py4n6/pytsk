#ifndef _PYTSK_MISC_H
#define _PYTSK_MISC_H

#include <assert.h>

#if defined( HAVE_INTTYPES_H )
#include <inttypes.h>
#elif !defined( _MSC_VER )
#include <stdint.h>
#endif

#if defined( WIN32 )
#include <winsock2.h>
#include <ws2tcpip.h>
#include <io.h>
#include <stdio.h>

#else
#include <sys/socket.h>
#include <netinet/tcp.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <time.h>
#include <libgen.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>

#endif /* defined( WIN32 ) */

#ifdef __cplusplus
extern "C" {
#endif

#if defined( _MSC_VER )
#define PYTSK_INLINE __inline
#elif defined( __BORLANDC__ ) || defined( __clang__ )
#define PYTSK_INLINE /* inline */
#else
#define PYTSK_INLINE inline
#endif

#if defined( _MSC_VER )
#define DLL_PUBLIC __declspec(dllexport)
#elif !defined( HEADERS_ONLY )
#define DLL_PUBLIC __attribute__ ((visibility("default")))
#else
#define DLL_PUBLIC
#endif

/* Used by class parser */
#if defined( _MSC_VER )
#define UNUSED
#else
#define UNUSED __attribute__((unused))
#endif

#if !defined( PYTSK3_ATTRIBUTE_UNUSED )
#if defined( __GNUC__ ) && __GNUC__ >= 3
#define PYTSK3_ATTRIBUTE_UNUSED  __attribute__ ((__unused__))
#else
#define PYTSK3_ATTRIBUTE_UNUSED
#endif
#endif

#if defined( _MSC_VER )
#define PYTSK3_UNREFERENCED_PARAMETER( parameter ) \
	UNREFERENCED_PARAMETER( parameter );
#else
#define PYTSK3_UNREFERENCED_PARAMETER( parameter ) \
	/* parameter */
#endif

#if !defined( _MSC_VER )
#ifdef min
#undef min
#endif
#define min(X, Y)  ((X) < (Y) ? (X) : (Y))

#ifdef max
#undef max
#endif
#define max(X, Y)  ((X) > (Y) ? (X) : (Y))

#endif /* if !defined( _MSC_VER ) */

#ifndef MIN
#define MIN(a,b) ((a)<(b)?(a):(b))
#endif

#ifndef MAX
#define MAX(a,b) ((a)>(b)?(a):(b))
#endif

#if defined( _MSC_VER ) 
#if defined( MS_WIN64 )
typedef __int64 ssize_t;
#else
typedef _W64 int ssize_t;
#endif
#endif

#if defined( WIN32 )
#define MSG_NOSIGNAL 0
typedef  unsigned long int in_addr_t;
typedef int bool;

#else
#define O_BINARY 0
typedef int bool;

#endif

#define true 1
#define false 0

#if !defined( HAVE_HTONLL ) && !defined( WIN32 )
uint64_t htonll(uint64_t n);
#define ntohll(x) htonll(x)
#endif

#ifdef __cplusplus
}
#endif

#endif


#ifndef _REPLACE_H_
#define _REPLACE_H_

#include <errno.h>

#include <string.h>

#if !defined( UINT_MAX )
#include <limits.h>
#endif

#define _PUBLIC_ extern

typedef int bool;

#define true 1
#define false 0

typedef unsigned char uint8_t;

#if !defined( MIN )
#define MIN(a,b) ((a)<(b)?(a):(b))
#endif

#if defined( _MSC_VER )

#define inline /* inline */ 

#if defined( MS_WIN64 )
typedef __int64 ssize_t;
#else
typedef _W64 int ssize_t;
#endif

#else

#define HAVE_VA_COPY

#endif /* defined( _MSC_VER ) */

#endif /* _REPLACE_H_ */

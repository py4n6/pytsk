/* 
   Unix SMB/CIFS implementation.
   replacement routines for broken systems
   Copyright (C) Andrew Tridgell 1992-1998
   Copyright (C) Jelmer Vernooij 2005-2008

     ** NOTE! The following LGPL license applies to the replace
     ** library. This does NOT imply that all of Samba is released
     ** under the LGPL
   
   This library is free software; you can redistribute it and/or
   modify it under the terms of the GNU Lesser General Public
   License as published by the Free Software Foundation; either
   version 3 of the License, or (at your option) any later version.

   This library is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
   Lesser General Public License for more details.

   You should have received a copy of the GNU Lesser General Public
   License along with this library; if not, see <http://www.gnu.org/licenses/>.
*/

#include "misc.h"

#ifndef HAVE_STRNLEN

/**
 Some platforms don't have strnlen
**/
 size_t rep_strnlen(const char *s, size_t max)
{
        size_t len;
  
        for (len = 0; len < max; len++) {
                if (s[len] == '\0') {
                        break;
                }
        }
        return len;  
}
#endif
  
#ifndef HAVE_STRNDUP
/**
 Some platforms don't have strndup.
**/
char *rep_strndup(const char *s, size_t n)
{
	char *ret;
	
	n = strnlen(s, n);
	ret = malloc(n+1);
	if (!ret)
		return NULL;
	memcpy(ret, s, n);
	ret[n] = 0;

	return ret;
}
#endif

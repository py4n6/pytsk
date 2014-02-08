/* Error functions.
 *
 * Copyright 2010, Michael Cohen <sucdette@gmail.com>.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#include <string.h>

#if !defined( WIN32 )
#include <pthread.h>
#endif

#include "aff4_errors.h"
#include "class.h"

#define ERROR_BUFF_SIZE 10240

// Windows version not truely threadsafe for now
#if defined( WIN32 )
static char global_error_buffer[ERROR_BUFF_SIZE];
static int global_error_type = 0;
#else
/** These slots carry the TLS error keys */
static pthread_key_t error_str_slot;
static pthread_once_t error_once = PTHREAD_ONCE_INIT;

static pthread_key_t error_value_slot;
#endif

#if defined( WIN32 )
static void error_init(void) {
  memset(global_error_buffer, 0, sizeof(global_error_buffer));
};

#else
static void error_init(void);

void error_dest(void *slot) {
  if(slot) talloc_free(slot);
};

void error_init(void) {
  // We create the error buffer slots
  if(pthread_key_create(&error_str_slot, error_dest) ||
     pthread_key_create(&error_value_slot, error_dest)) {
    printf("Unable to set up TLS variables\n");
    abort();
  };
};
#endif

DLL_PUBLIC void *aff4_raise_errors(int t, char *reason, ...) {
  char *error_buffer;
  char tmp[ERROR_BUFF_SIZE];
  // This has to succeed:
  int *type = aff4_get_current_error(&error_buffer);

  if(reason) {
    va_list ap;
    va_start(ap, reason);

    vsnprintf(tmp, ERROR_BUFF_SIZE-1, reason,ap);
    tmp[ERROR_BUFF_SIZE-1]=0;
    va_end(ap);
  };

  if(*type == EZero) {
    *error_buffer = 0;

    //update the error type
    *type = t;
  } else {
    strncat(error_buffer, "\n", ERROR_BUFF_SIZE -1 );
  };

  strncat(error_buffer, tmp, ERROR_BUFF_SIZE-1);

  return NULL;
};

#if defined( WIN32 )
DLL_PUBLIC int *aff4_get_current_error(char **error_buffer) {
  if(error_buffer != NULL) {
    *error_buffer = global_error_buffer;
  };
  return &global_error_type;
};

#else
DLL_PUBLIC int *aff4_get_current_error(char **error_buffer) {
  int *type;

  (void) pthread_once(&error_once, error_init);
  type = pthread_getspecific(error_value_slot);

  // This is optional
  if(error_buffer != NULL) {
    *error_buffer = pthread_getspecific(error_str_slot);

    // If TLS buffers are not set we need to create them
    // TODO: the TLS buffers need to be freed on exit.
    if(*error_buffer == NULL) {
      *error_buffer = talloc_size(NULL, ERROR_BUFF_SIZE);
      pthread_setspecific(error_str_slot, *error_buffer);
    };
  };

  if(!type) {
    type = talloc_size(NULL, ERROR_BUFF_SIZE);
    pthread_setspecific(error_value_slot, type);
  };

  return type;
};
#endif

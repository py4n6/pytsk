/*
** error.c
** 
** Made by (mic)
** Login   <mic@laptop>
** 
** Started on  Mon Mar 15 20:45:09 2010 mic
** Last update Sun May 12 01:17:25 2002 Speed Blue
*/

//#include "misc.h"
#include <pthread.h>
#include "class.h"
#include <string.h>
#include "aff4_errors.h"

#define ERROR_BUFF_SIZE 10240

/** These slots carry the TLS error keys */
static pthread_key_t error_str_slot;
static pthread_once_t error_once = PTHREAD_ONCE_INIT;

static pthread_key_t error_value_slot;

static void error_init(void);

void error_dest(void *slot) {
  if(slot) talloc_free(slot);
};

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

DLL_PUBLIC int *aff4_get_current_error(char **error_buffer) {
  int *type;

  (void) pthread_once(&error_once, error_init);
  type = pthread_getspecific(error_value_slot);

  // This is optional
  if(error_buffer) {
    *error_buffer = pthread_getspecific(error_str_slot);

  // If TLS buffers are not set we need to create them
    if(!*error_buffer) {
      *error_buffer =talloc_size(NULL, ERROR_BUFF_SIZE);
      pthread_setspecific(error_str_slot, *error_buffer);
    };
  };

  if(!type) {
    type = talloc_size(NULL, ERROR_BUFF_SIZE);
    pthread_setspecific(error_value_slot, type);
  };

  return type;
};

void error_init(void) {
  // We create the error buffer slots
  if(pthread_key_create(&error_str_slot, error_dest) ||
     pthread_key_create(&error_value_slot, error_dest)) {
    printf("Unable to set up TLS variables\n");
    abort();
  };
};

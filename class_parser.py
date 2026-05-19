#!/usr/bin/env python3
#
# Copyright 2010, Michael Cohen <scudette@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Documentation regarding the Python bounded code.

This code originally released as part of the AFF4 project
(http://code.google.com/p/aff4/).

Memory Management
=================

AFF4 uses a reference count system for memory management similar in many ways to the
native Python system. The basic idea is that memory returned by the library always
carries a new reference. When the caller is done with the memory, they must call
aff4_free() on the memory, afterwhich the memory is considered invalid. The memory may
still not be freed at this point depending on its total reference count.

New references may be taken to the same memory at any time using the aff4_incref()
function. This increases the reference count of the object, and prevents it from being
really freed until the correct number of aff4_free() calls are made to it.

This idea is important for example in the following sequence:

FileLikeObject fd = resolver->create(resolver, "w");
RDFURN uri = fd->urn;

Now uri hold a reference to the urn attribute of fd, but that attribute is actually
owned by fd. If fd is freed in future, e.g. (the close method actually frees the fd
implicitely):

fd->close(fd);

Now the uri object is dangling. To prevent fd->urn from disappearing when fd is freed,
we need to take another reference to it:

FileLikeObject fd = resolver->create(resolver, "w");
RDFURN uri = fd->urn;
aff4_incref(uri);

fd->close(fd);

Now uri is valid (but fd is no longer valid). When we are finished with uri we just
call:

aff4_free(uri);


Python Integration
------------------

For every AFF4 object, we create a Python wrapper object of the corresponding type. The
wrapper object contains Python wrapper methods to allow access to the AFF4 object
methods, as well as getattr methods for attributes. It is very important to allow
Python to inherit from C classes directly - this requires every internal C method call
to be diverted to the Python object.

The C object looks like this normally:

struct obj {
    __class__ pointer to static struct initialised with C method pointers

... Some private members
... Attributes;

/* Following are the methods */
    int (*method)(struct obj *self, ....);
};

I.e. when the method is called the struct.method member is dereferenced to find the
location of the function handling it, the object is stuffed into the first arg, and the
parameters are stuffed into following args.

Directing Python calls
----------------------

The Python object which is created is a proxy for the c object. When Python methods are
called in the Python object, they need to be directed into the C structure and a C call
must be made, then the return value must be reconverted into Python objects and
returned into Python. This occurs automatically by the wrapper:

struct PythonWrapper {
      PyObject_HEAD
      void *base;
};

When a Python method is called on this new Python type this is what happens:

 1) The method name is looked up in the PyMethodDef struct as per normal.

 2) If the method is recognised as a valid method the Python wrapper
    function is called (pyCLASSNAME_method)

 3) This method is broken into the general steps:

PyObject *pyCLASSNAME_method(PythonWrapper self, PyObject *args, PyObject *kwds) {
    set up c declerations for all args - call .definition() on all the args and return
    type

    parse argument using PyArg_ParseTupleAndKeywords

    Precall preparations

    Make the C call

    Post call processing of the returned value (check for errors etc)

    Convert the return value to a Python object using:
    return_type.to_Python_object()

    return the Python object or raise an exception
};

So the aim of the wrapper function is to convert Python args to C args, find the C
method corresponding to the method name by dereferencing the c object and then call it.


The problem now is what happens when a C method internally calls another method. This
is a problem because the C method has no idea its running within Python and so will
just call the regular C method that was there already. This makes it impossible to
subclass the C class and update the C method with a Python method. What we really want
is when a C method is called internally, we want to end up calling the Python object
instead to allow a purely Python implementation to override the C method.

This happens by way of a ProxiedMethod - A proxied method is in a sense the reverse of
the wrapper method:

return_type ProxyCLASSNAME_method(CCLASSNAME self, ....) {
   Take all C args and create Python objects from them

   Dereference the object extension ((Object) self)->extension to
   obtain the Python object which wraps this C class.

   If an extension does not exist, just call the method as normal,
   otherwise make a Python call on the wrapper object.

   Convert the returned Python object to a C type and return it.
};

To make all this work we have the following structures:
struct PythonWrapper {
  PyObject_HEAD
  struct CCLASSNAME *base

       - This is a copy of the item, with all function pointer pointing at proxy
         functions. We can always get the original C function pointers through
         "base->__class__"

       - We also set the base object extension to be the Python object:
         "((Object) base)->extension = PythonWrapper". This allows us to get back the
         Python object from base.
};


When a Python method is invoked, we use cbase to find the C method pointer, but we pass
to it base:

self->base->__class__->method(self->base, ....)

base is a proper C object which had its methods dynamically replaced with proxies. Now
if an internal C method is called, the method will dereference base and retrieve the
proxied method. Calling the proxied method will retreive the original Python object
from the object extension and make a Python call.

In the case where a method is not overridden by Python, internal C method calls will
generate an unnecessary conversion from C to Python and then back to C.

Memory management in Python extension
-------------------------------------

When calling a method which returns a new reference, we just store the reference in the
"base" member of the Python object. When Python garbage collects our Python object, we
call aff4_free() on it.

The getattr method creates a new Python wrapper object of the correct type, and sets
its base attribute to point at the target AFF4 object. We then aff4_incref() the target
to ensure that it does not get freed until we are finished with it.


   Python Object
    -----
   |  P1 |   C Object
   | Base|-->+------+
   |     |   |  C1  |
   |     |   |      |
    -----    |Member|--------------+-->+----+
             +------+              |   | C2 |
                                   |   |    |
                Getattr  -------   |   |    |
                Member  |  P2   |  |   +----+
                        | Base  |--+ New reference
                         -------
                        Python Object

   Figure 1: Python object 1 owns C1's memory (when P1 is GC'ed C1 is freed). A
             reference to a member of C1 is made via P1's getattr method. The getattr
             method creates P2 to provide access to C2 by setting base to C2's address.
             We need to guarantee however, that C2 will not be freed suddenly (e.g. if
             C1 is freed). We therefore increase C2's reference count using
             "aff4_incref()".
"""

import io
import re
import sys

import lexer

# This file does not follow the naming convention specified in .pylintrc.
# pylint: disable=invalid-name


DEBUG = False

# The pytsk3 version.
VERSION = "20260519"

# These functions are used to manage library memory.
FREE = "aff4_free"
INCREF = "aff4_incref"
CURRENT_ERROR_FUNCTION = "aff4_get_current_error"
CONSTANTS_DENYLIST = ["TSK3_H_"]

# Some constants.
DOCSTRING_RE = re.compile("[ ]*\n[ \t]+[*][ ]?")


class BaseCodeGenerator:
    """Base code generator."""

    _DEBUG = DEBUG

    def format_as_docstring(self, string):
        """Formats a string as docstring."""
        # Remove C/C++ comment code statements.
        string = DOCSTRING_RE.sub("\n", string)
        byte_string = string.encode("unicode-escape")

        # Escapes double quoted string. We need to run this after unicode-escape to
        # prevent this operation to escape the escape character (\). In Python 3 the
        # replace method requires the arguments to be byte strings.
        byte_string = byte_string.replace(b'"', b'\\"')

        # Make sure to return the string a Unicode otherwise in Python 3 the string
        # is prefixed with b when written or printed.
        return byte_string.decode("utf-8")

    def log(self, message):
        """Logs a message to stderr."""
        if self._DEBUG:
            sys.stderr.write(f"{message:s}\n")


class Module(BaseCodeGenerator):
    """Python module code generator."""

    _PRIVATE_FUNCTIONS_TEMPLATE = """
/* The following is a static array mapping CCLASS() pointers to their Python wrappers.
 * This is used to allow the correct wrapper to be chosen depending on the object type
 * found - regardless of the prototype.
 *
 * This is basically a safer way for us to cast the correct Python type depending on
 * context rather than assuming a type based on the .h definition. For example consider
 * the function:
 *
 * AFFObject Resolver.open(uri, mode)
 *
 * The .h file implies that an AFFObject object is returned, but this is not true as
 * most of the time an object of a derived C class will be returned. In C we cast the
 * returned value to the correct type. In the Python wrapper we just instantiate the
 * correct Python object wrapper at runtime depending on the actual returned type. We
 * use this lookup table to do so.
 */

/* std::atomic is used so a re-import (subinterpreter or importlib.reload) cannot expose
 * a half-zeroed table to a concurrent new_class_wrapper reader. Writers use release /
 * readers acquire so seeing the bumped count implies seeing the matching
 * python_wrappers[] entry.
 */
static std::atomic<int> TOTAL_CCLASSES(0);

#define CONSTRUCT_INITIALIZE(cclass, virt_cclass, constructor, object, ...) \\
    (cclass)(((virt_cclass) (&__ ## cclass))->constructor(object, ## __VA_ARGS__))

#undef BUFF_SIZE
#define BUFF_SIZE 10240

/* Generic wrapper type
 */
typedef struct Gen_wrapper_t *Gen_wrapper;
struct Gen_wrapper_t {{
    PyObject_HEAD

    void *base;

    /* Value to indicate the base is a Python object.
     */
    int base_is_python_object;

    /* Value to indicate the base is managed internal.
     */
    int base_is_internal;

    PyObject *python_object1;
    PyObject *python_object2;
}};

static struct python_wrapper_map_t {{
    Object class_ref;
    PyTypeObject *python_type;
    void (*initialize_proxies)(Gen_wrapper self, void *item);
}} python_wrappers[{classes_length:d}];

/* Cycle-collection support shared by every Gen_wrapper-shaped type (real classes and
 * struct wrappers; not enums, which keep their own layout). python_object1/2 hold
 * strong refs to other wrappers that can reference back through Python attributes,
 * without GC support the cycle leaks for the process lifetime.
 */
static int Gen_wrapper_traverse(PyObject *self, visitproc visit, void *arg) {{
    Gen_wrapper g = (Gen_wrapper) self;
    Py_VISIT(g->python_object1);
    Py_VISIT(g->python_object2);
    if(g->base_is_python_object != 0 && g->base != NULL) {{
        Py_VISIT((PyObject *) g->base);
    }}
    return 0;
}}

static int Gen_wrapper_clear(PyObject *self) {{
    Gen_wrapper g = (Gen_wrapper) self;
    Py_CLEAR(g->python_object1);
    Py_CLEAR(g->python_object2);
    if(g->base_is_python_object != 0 && g->base != NULL) {{
        PyObject *tmp = (PyObject *) g->base;
        g->base = NULL;
        Py_DECREF(tmp);
    }}
    return 0;
}}

/* Create the relevant wrapper from the item based on the lookup table.
 *
 * If parent is non-NULL, the wrapped child takes a strong reference to it via
 * python_object1. This keeps the parent Python wrapper (and therefore its underlying
 * libtsk handle) alive for as long as the child exists, which matters under
 * free-threaded Python where a different thread may drop the parent's last visible
 * reference while this thread is still using a child object derived from it.
 */
Gen_wrapper new_class_wrapper(Object item, int item_is_python_object, PyObject *parent) {{
    Gen_wrapper result = NULL;
    Object cls = NULL;
    struct python_wrapper_map_t *python_wrapper = NULL;
    int cls_index = 0;

    // Return a Py_None object for a NULL pointer
    if(item == NULL) {{
        Py_IncRef((PyObject *) Py_None);
        return (Gen_wrapper) Py_None;
    }}
    // Search for subclasses
    int total = TOTAL_CCLASSES.load(std::memory_order_acquire);

    for(cls = (Object) item->__class__; cls != cls->__super__; cls = cls->__super__) {{
        for(cls_index = 0; cls_index < total; cls_index++) {{
            python_wrapper = &(python_wrappers[cls_index]);

            if(python_wrapper->class_ref == cls) {{
                PyErr_Clear();

                /* PyObject_GC_New: the type carries Py_TPFLAGS_HAVE_GC so
                 * the object must be allocated through the GC machinery;
                 * GC_Track is deferred until python_object1/2 and base are
                 * fully wired so traverse never sees a half-built wrapper.
                 */
                result = PyObject_GC_New(struct Gen_wrapper_t, python_wrapper->python_type);
                if(result == NULL) {{
                    return NULL;
                }}
                result->base = item;
                result->base_is_python_object = item_is_python_object;
                result->base_is_internal = 1;
                result->python_object1 = NULL;
                result->python_object2 = NULL;

                if(parent != NULL) {{
                    Py_IncRef(parent);
                    result->python_object1 = parent;
                }}

                python_wrapper->initialize_proxies(result, (void *) item);

                PyObject_GC_Track((PyObject *) result);
                return result;
            }}
        }}
    }}
    PyErr_Format(PyExc_RuntimeError, "Unable to find a wrapper for object %s", NAMEOF(item));

    return NULL;
}}

typedef void (*function_initialize_Gen_wrapper_t)(Gen_wrapper, void*);

static PyObject *resolve_exception(char **error_buff) {{
    int *type = (int *){get_current_error:s}(error_buff);

    switch(*type) {{
        case EProgrammingError:
            return PyExc_SystemError;
        case EKeyError:
            return PyExc_KeyError;
        case ERuntimeError:
            return PyExc_RuntimeError;
        case EInvalidParameter:
            return PyExc_TypeError;
        case EWarning:
            return PyExc_AssertionError;
        case EIOError:
            return PyExc_IOError;
        default:
            return PyExc_RuntimeError;
    }}
}}

static int type_check(PyObject *obj, PyTypeObject *type) {{
    PyTypeObject *tmp = NULL;

    // Recurse through the inheritance tree and check if the types are expected
    if(obj) {{
        for(tmp = Py_TYPE(obj);
            tmp && tmp != &PyBaseObject_Type;
            tmp = tmp->tp_base) {{
            if(tmp == type) return 1;
        }}
    }}
    return 0;
}}

static int check_error() {{
    char *buffer = NULL;
    int *error_type = (int *) aff4_get_current_error(&buffer);

    if(*error_type != EZero) {{
        PyObject *exception = resolve_exception(&buffer);

        if(buffer != NULL) {{
            PyErr_Format(exception, "%s", buffer);
        }} else {{
            PyErr_Format(exception, "Unable to retrieve exception reason.");
        }}
        ClearError();
        return 1;
    }}
    return 0;
}}

/* This function checks if a method was overridden in self over a
 * method defined in type. This is used to determine if a Python class is
 * extending this C type. If not, a proxy function is not written and C
 * calls are made directly.
 *
 * This is an optimization to eliminate the need for a call into Python
 * in the case where Python objects do not actually extend any methods.
 *
 * We basically just iterate over the MRO and determine if a method is
 * defined in each level until we reach the base class.
 */
static int check_method_override(PyObject *self, PyTypeObject *type, const char *method) {{
    struct _typeobject *ob_type = NULL;
    PyObject *mro = NULL;
    PyObject *py_method = NULL;
    PyObject *item_object = NULL;
    PyObject *dict = NULL;
    Py_ssize_t item_index = 0;
    Py_ssize_t number_of_items = 0;
    int found = 0;

    ob_type = Py_TYPE(self);
    if(ob_type == NULL ) {{
      return 0;
    }}
    mro = ob_type->tp_mro;

    py_method = PyUnicode_FromString(method);
    if(py_method == NULL) {{
        return 0;
    }}
    number_of_items = PySequence_Size(mro);

    for(item_index = 0; item_index < number_of_items; item_index++) {{
        int contains_result = 0;
        item_object = PySequence_GetItem(mro, item_index);
        if(item_object == NULL) {{
            break;
        }}

        // Ok - we got to the base class - finish up
        if(item_object == (PyObject *) type) {{
            Py_DecRef(item_object);
            break;
        }}
        /* Extract the dict and check if it contains the method (the
         * dict is not a real dictionary so we can not use
         * PyDict_Contains).
         */
        dict = PyObject_GetAttrString(item_object, "__dict__");
        if(dict != NULL) {{
            contains_result = PySequence_Contains(dict, py_method);
            if(contains_result > 0) {{
                found = 1;
            }}
        }}
        Py_DecRef(dict);
        Py_DecRef(item_object);

        if(found != 0) {{
            break;
        }}
    }}
    Py_DecRef(py_method);
    PyErr_Clear();

    return found;
}}

/* Fetches a Python exception.
 *
 * Python 3.12+ uses PyErr_GetRaisedException and PyErr_SetRaisedException. PyErr_Fetch
 * and PyErr_Restore triple were deprecated in 3.12 and removed in 3.14. Given
 * normalization races they cannot be used under free-threading.
 *
 * Pre-3.12 support has been retained for Python 3.10 and 3.11 compatibility.
 */
void pytsk_fetch_error(void) {{
#if PY_VERSION_HEX >= 0x030C0000
    PyObject *raised_exception = NULL;
#else
    PyObject *exception_traceback = NULL;
    PyObject *exception_type = NULL;
    PyObject *exception_value = NULL;
#endif
    PyObject *exception_repr = NULL;
    PyObject *string_object = NULL;
    char *str_c = NULL;
    char *error_str = NULL;
    int *error_type = (int *) {get_current_error:s}(&error_str);

    PyObject *utf8_string_object  = NULL;

    /* Fetch the exception state and convert it to a string.
     */
#if PY_VERSION_HEX >= 0x030C0000
    raised_exception = PyErr_GetRaisedException();
    exception_repr = raised_exception;
#else
    PyErr_Fetch(&exception_type, &exception_value, &exception_traceback);
    exception_repr = exception_value;
#endif

    /* NULL on the legacy path means PyErr_SetNone(type) raised without a value, e.g.
     * KeyboardInterrupt); on the modern path means no exception was actually set.
     */
    if(exception_repr == NULL) {{
        if(error_str != NULL) {{
            const char *placeholder = "Python exception raised without value";
            size_t placeholder_len = strlen(placeholder);
            if(placeholder_len > (size_t)(BUFF_SIZE - 1)) {{
                placeholder_len = (size_t)(BUFF_SIZE - 1);
            }}
            memcpy(error_str, placeholder, placeholder_len);
            error_str[placeholder_len] = 0;
        }}
        *error_type = ERuntimeError;
#if PY_VERSION_HEX >= 0x030C0000
        PyErr_SetRaisedException(raised_exception);
#else
        PyErr_Restore(exception_type, exception_value, exception_traceback);
#endif
        return;
    }}
    string_object = PyObject_Repr(exception_repr);

    if(string_object != NULL) {{
        utf8_string_object = PyUnicode_AsUTF8String(string_object);
    }}
    if(utf8_string_object != NULL) {{
        str_c = PyBytes_AsString(utf8_string_object);
    }}
    if(str_c != NULL) {{
        strncpy(error_str, str_c, BUFF_SIZE-1);
        error_str[BUFF_SIZE - 1] = 0;
        *error_type = ERuntimeError;
    }} else {{
        /* Repr/encode failed; record a generic message so callers
         * still observe ERuntimeError instead of EZero (which would
         * make check_error() report success).
         */
        if(error_str != NULL) {{
            const char *placeholder = "Python exception (repr failed)";
            size_t placeholder_len = strlen(placeholder);

            if(placeholder_len > (size_t)(BUFF_SIZE - 1)) {{
                placeholder_len = (size_t)(BUFF_SIZE - 1);
            }}
            memcpy(error_str, placeholder, placeholder_len);
            error_str[placeholder_len] = 0;
        }}
        *error_type = ERuntimeError;
    }}
#if PY_VERSION_HEX >= 0x030C0000
    PyErr_SetRaisedException(raised_exception);
#else
    PyErr_Restore(exception_type, exception_value, exception_traceback);
#endif

    if( utf8_string_object != NULL ) {{
        Py_DecRef(utf8_string_object);
    }}
    if(string_object != NULL) {{
        Py_DecRef(string_object);
    }}
    return;
}}

/* Copies a Python int or long object to an unsigned 64-bit value
 */
uint64_t integer_object_copy_to_uint64(PyObject *integer_object) {{
#if defined( HAVE_LONG_LONG )
    PY_LONG_LONG long_value = 0;
#else
    long long_value = 0;
#endif
    int result = 0;

    if(integer_object == NULL) {{
        PyErr_Format(PyExc_ValueError, "Missing integer object");

        return (uint64_t) -1;
    }}
    PyErr_Clear();

    result = PyObject_IsInstance(integer_object, (PyObject *) &PyLong_Type);

    if(result == -1) {{
        pytsk_fetch_error();

        return (uint64_t) -1;

    }} else if(result != 0) {{
        PyErr_Clear();

#if defined( HAVE_LONG_LONG )
    long_value = PyLong_AsUnsignedLongLong(integer_object);
#else
    long_value = PyLong_AsUnsignedLong(integer_object);
#endif
        /* PyLong_AsUnsignedLong / PyLong_AsUnsignedLongLong returns
         * (unsigned)-1 and sets OverflowError when the value does
         * not fit. Surfacing the original exception is more useful
         * than continuing into the generic "out of bounds" path
         * below, which would clobber the OverflowError with a fresh
         * ValueError.
         */
        if(PyErr_Occurred()) {{
            pytsk_fetch_error();

            return (uint64_t) -1;
        }}
    }}
    if(result == 0) {{
        if(PyErr_Occurred()) {{
            pytsk_fetch_error();

            return (uint64_t) -1;
        }}
    }}
#if defined( HAVE_LONG_LONG )
#if ( SIZEOF_LONG_LONG > 8 )
    if((long_value < (PY_LONG_LONG) 0) || (long_value > (PY_LONG_LONG) UINT64_MAX)) {{
#else
    if(long_value < (PY_LONG_LONG) 0) {{
#endif
        PyErr_Format(PyExc_ValueError, "Integer object value out of bounds");

        return (uint64_t) -1;
    }}
#else
#if ( SIZEOF_LONG > 8 )
    if((long_value < (long) 0) || (long_value > (long) UINT64_MAX)) {{
#else
    if(long_value < (PY_LONG_LONG) 0) {{
#endif
        PyErr_Format(PyExc_ValueError, "Integer object value out of bounds");

        return (uint64_t) -1;
    }}
#endif
    return (uint64_t) long_value;
}}

"""

    _MODULE_INITIALIZATION_TEMPLATE = """\
/* Retrieves the {module:s} version
 * Returns a Python object if successful or NULL on error
 */
PyObject *{module:s}_get_version(PyObject *self, PyObject *arguments) {{
    const char *errors = NULL;
    return(PyUnicode_DecodeUTF8("{version:s}", (Py_ssize_t) {version_length:d}, errors));
}}

static PyMethodDef {module:s}_module_methods[] = {{
    {{ "get_version",
        (PyCFunction) {module:s}_get_version,
        METH_NOARGS,
        "get_version() -> String\\n"
        "\\n"
        "Retrieves the version." }},

    {{NULL, NULL, 0, NULL}}  /* Sentinel */
}};


/* The {module:s} module definition
 */
PyModuleDef {module:s}_module_definition = {{
	PyModuleDef_HEAD_INIT,

	/* m_name */
	"{module:s}",
	/* m_doc */
	"Python {module:s} module.",
	/* m_size */
	-1,
	/* m_methods */
	{module:s}_module_methods,
	/* m_reload */
	NULL,
	/* m_traverse */
	NULL,
	/* m_clear */
	NULL,
	/* m_free */
	NULL,
}};


/* Initializes the {module:s} module
 */
PyObject * PyInit_{module:s}(void) {{
    PyGILState_STATE gil_state;

    PyObject *module = NULL;
    PyObject *d = NULL;
    PyObject *tmp = NULL;

    /* Create the module
     * This function must be called before grabbing the GIL
     * otherwise the module will segfault on a version mismatch
     */
    module = PyModule_Create(
        &{module:s}_module_definition );
    if (module == NULL) {{
        return(NULL);
    }}

#ifdef Py_GIL_DISABLED
    /* Declare this module safe for free-threaded Python
     * Without this call, CPython force-enables
     * the GIL for our module at import time on
     * free-threaded builds, which would serialize every
     * pytsk3 call and defeat the point of free-threading.
     * The symbol is only declared when Py_GIL_DISABLED is set
     */
    PyUnstable_Module_SetGIL(module, Py_MOD_GIL_NOT_USED);
#endif

    d = PyModule_GetDict(module);

    gil_state = PyGILState_Ensure();

    /* Relaxed: per-class registration's release fetch_add
     * carries the happens-before for any acquire-load reader.
     */
    TOTAL_CCLASSES.store(0, std::memory_order_relaxed);
"""

    def __init__(self, name):
        """Initializes the code generator."""
        super().__init__()
        self.active_structs = set()
        self.classes = {}
        self.constants_denylist = CONSTANTS_DENYLIST
        self.constants = set()
        self.files = []
        self.function_definitions = set()
        self.headers = ""
        self.init_string = ""
        self.name = name
        self.public_api = None

    def add_class(self, cls, type_class):
        """Add a class and register it with the type dispatcher."""
        self.classes[cls.class_name] = cls

        TypeDispatcher.register(cls.class_name, type_class)

    def add_constant(self, constant, data_type="numeric"):
        """This will be called to add #define constant macros."""
        self.constants.add((constant, data_type))

    def get_string(self):
        """Retrieves a string representation."""
        result = f"Module {self.name:s}\n"
        classes_list = list(self.classes.values())
        classes_list.sort(key=lambda cls: cls.class_name)
        for cls in classes_list:
            if cls.is_active():
                class_name = cls.get_string()
                result += f"    {class_name:s}\n"

        constants_list = list(self.constants)
        constants_list.sort()
        result += "Constants:\n"
        for name, _ in constants_list:
            result += f" {name:s}\n"

        return result

    def initialize_class(self, class_name, out, done=None):
        """Write class initialization code into the main init function.

        Args:
          class_name (str): name of the class to write.
          out (IO): ouput to write to.
          done (Optional[bool]): value to indicate all class initialization
              code has been written to output.
        """
        if done and class_name in done:
            return

        done.add(class_name)

        cls = self.classes[class_name]
        if cls.is_active():
            base_class = self.classes.get(cls.base_class_name)
            if base_class and base_class.is_active():
                # We have a base class - ensure it gets written out first.
                self.initialize_class(cls.base_class_name, out, done=done)

                # Now assign ourselves as derived from them.
                out.write(
                    f"    {class_name:s}_Type.tp_base = "
                    f"&{cls.base_class_name:s}_Type;"
                )

            out.write(
                f"\n"
                f"    /* Initialize: {class_name:s} */\n"
                f"    {class_name:s}_Type.tp_new = PyType_GenericNew;\n"
            )
            if isinstance(cls, Enum):
                out.write(
                    f"    if ({class_name:s}_init_type(&{class_name:s}_Type) != 1) {{\n"
                    f"        goto on_error;\n"
                    f"    }}\n"
                )

            out.write(
                f"    if (PyType_Ready(&{class_name:s}_Type) < 0) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
                f"    if (PyModule_AddType(module, &{class_name:s}_Type) < 0) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
            )

    def initialization(self):
        """Generates initializiation code of the C/C++ type."""
        result = self.init_string + (
            "\n"
            "talloc_set_log_fn((void (*)(const char *)) printf);\n"
            "// DEBUG: talloc_enable_leak_report();\n"
            "// DEBUG: talloc_enable_leak_report_full();\n"
        )
        for cls in self.classes.values():
            if cls.is_active():
                result += cls.initialize()

        return result

    def private_functions(self):
        """Generates private functions code of the C/C++ type."""
        values_dict = {
            "classes_length": len(self.classes) + 1,
            "get_current_error": CURRENT_ERROR_FUNCTION,
        }
        return self._PRIVATE_FUNCTIONS_TEMPLATE.format(**values_dict)

    def write(self, out):
        """Generates code of the C/C++ type."""
        # Write the headers
        if self.public_api:
            self.public_api.write(
                "#ifdef BUILDING_DLL\n"
                '#include "misc.h"\n'
                "#else\n"
                '#include "aff4_public.h"\n'
                "#endif\n"
            )

        # Prepare all classes
        for cls in self.classes.values():
            cls.prepare()

        filenames = "".join([f" * {filename:s}\n" for filename in self.files])
        classes = self.get_string()

        out.write(
            f"/*************************************************************\n"
            f" * Autogenerated module {self.name:s}\n"
            f" *\n"
            f" * This module was autogenerated from the following files:\n"
            f"{filenames:s}"
            f" *\n"
            f" * This module implements the following classes:\n"
            f"{classes:s}"
            f" ************************************************************/\n"
            "\n"
        )
        out.write(self.headers)
        out.write(
            "\n"
            "#ifdef __cplusplus\n"
            "#include <atomic>\n"
            'extern "C" {\n'
            "#endif\n"
            "\n"
            "#include <Python.h>\n"
        )
        out.write(self.private_functions())

        for cls in self.classes.values():
            if cls.is_active():
                out.write(
                    f"/******************** {cls.class_name:s} ***********************/"
                )
                cls.struct(out)
                cls.prototypes(out)

        out.write(
            "/*****************************************************\n"
            " *           Implementation\n"
            " ****************************************************/\n"
            "\n"
        )
        for cls in self.classes.values():
            if cls.is_active():
                cls.PyMethodDef(out)
                cls.PyGetSetDef(out)
                cls.PyTypeObject(out)

        for cls in self.classes.values():
            if cls.is_active():
                cls.code(out)

        # Write the module initialization.
        values_dict = {
            "module": self.name,
            "version": VERSION,
            "version_length": len(VERSION),
        }
        out.write(self._MODULE_INITIALIZATION_TEMPLATE.format(**values_dict))

        # The trick is to initialize the classes in order of their
        # inheritance. The following code will order initializations
        # according to their inheritance tree
        done = set()
        for class_name in self.classes:
            self.initialize_class(class_name, out, done=done)

        # Make sure the constants are sorted so builds of pytsk3.c are reproducible.
        for constant, data_type in sorted(self.constants):
            if data_type not in ("integer", "string"):
                out.write(
                    f"    /* I don't know how to convert {constant:s} type "
                    f"{data_type:s} */\n"
                )
                continue

            if data_type == "integer":
                out.write(
                    f"    tmp = PyLong_FromUnsignedLongLong((uint64_t) {constant:s});\n"
                )
            elif constant == "TSK_VERSION_STR":
                out.write(f"    tmp = PyUnicode_FromString((char *){constant:s});\n")
            else:
                out.write(f"    tmp = PyBytes_FromString((char *){constant:s});\n")

            out.write(
                f'    PyDict_SetItemString(d, "{constant:s}", tmp);\n'
                f"    Py_DecRef(tmp);\n"
            )

        out.write(self.initialization())
        out.write(
            "    PyGILState_Release(gil_state);\n"
            "\n"
            "	return module;\n"
            "\n"
            "on_error:\n"
            "	PyGILState_Release(gil_state);\n"
            "\n"
            "	return NULL;\n"
            "}\n"
            "\n"
            "#ifdef __cplusplus\n"
            "}\n"
            "#endif\n"
        )


class Type(BaseCodeGenerator):
    """Type code generator."""

    _ASSIGN_TEMPLATE = """\
Py_BEGIN_ALLOW_THREADS
{name:s} = {call:s};
Py_END_ALLOW_THREADS
"""

    _POST_CALL_TEMPLATE = """\
if(check_error()) {
    goto on_error;
}
"""

    BUILDSTR = "O"

    # TODO: clean up active, currently used as both class and instance variable.
    active = True

    def __init__(self, name, data_type, *unused_args, **kwargs):
        """Initializes the code generator."""
        super().__init__()
        self.additional_args = kwargs
        self.attributes = set()
        self.error_value = "return 0;"
        self.interface = None
        self.name = name
        self.sense = "IN"
        self.type = data_type

    def assign(self, call, unused_method, target=None, **unused_kwargs):
        """Generates code to assign the C/C++ type."""
        values_dict = {"call": call, "name": target or self.name}

        return self._ASSIGN_TEMPLATE.format(**values_dict)

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}"

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return self.name

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        return f"{self.type:s} {self.name:s} "

    def definition(self, default=None, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        if default:
            return f"    {self.type:s} {self.name:s} = {default:s};\n"

        if "array_size" in self.additional_args:
            return (
                f"    int array_index = 0;\n"
                f"    {self.type:s} UNUSED *{self.name:s};\n"
            )

        return f"    {self.type:s} UNUSED {self.name:s};\n"

    def from_python_object(
        self, unused_source, unused_destination, unused_method, **unused_kwargs
    ):
        """Generates code to convert a C/C++ type into a Python object."""
        return ""

    def get_string(self):
        """Retrieves a string representation."""
        if self.name == "func_return":
            return self.type

        if "void" in self.type:
            return ""

        return f"{self.type:s} : {self.name:s}"

    def local_definition(self, **unused_kwargs):
        """Generates code to local define the C/C++ type."""
        return ""

    def passthru_call(self):
        """Returns how we should call the function when simply passing args directly"""
        return self.call_arg()

    def pre_call(self, unused_method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        return ""

    def post_call(self, unused_method):
        """Generates code needed after a function call for the C/C++ type."""
        result = self._POST_CALL_TEMPLATE

        if "DESTRUCTOR" in self.attributes:
            result += (
                "self->base = NULL;  /* DESTRUCTOR - C object no longer valid */\n"
            )

        return result

    def python_name(self):
        """Retrieves the Python name of the C/C++ type."""
        return self.name

    def python_proxy_post_call(self):
        """This is called after a proxy call."""
        return ""

    def return_value(self, value):
        """Generates code of the C/C++ type as a return value."""
        return f"return {value!s};"

    def returned_python_definition(self, **kwargs):
        """Generates code to define the C/C++ type."""
        return self.definition(**kwargs)


class String(Type):
    """String type code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """
{{
    char *buff = NULL;
    Py_ssize_t length = 0;

    PyErr_Clear();

    if(PyBytes_AsStringAndSize({source:s}, &buff, &length) == -1) {{
        goto on_error;
    }}
    {destination:s} = (char *) talloc_size({context:s}, length + 1);
    if({destination:s} == NULL) {{
        PyErr_NoMemory();
        goto on_error;
    }}
    memcpy({destination:s}, buff, length);
    {destination:s}[length] = 0;
}};
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();

    if(!{name:s}) {{
        Py_IncRef(Py_None);
        {result:s} = Py_None;
    }} else {{
        {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});
        if(!{result:s}) {{
            goto on_error;
        }}
    }}
"""

    BUILDSTR = "s"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.error_value = "return NULL;"
        self.interface = "string"
        self.length = f"strlen({name:s})"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}"

    def from_python_object(
        self, source, destination, method, context="NULL", **unused_kwargs
    ):
        """Generates code to convert a C/C++ type into a Python object."""
        method.error_set = True

        values_dict = {"context": context, "destination": destination, "source": source}

        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result,
        }
        result = self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

        if "BORROWED" not in self.attributes and "BORROWED" not in kwargs:
            result += f"talloc_unlink(NULL, {name:s});\n"

        return result


class ZString(String):
    """Null terminated string type code generator."""

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.interface = "null_terminated_string"

    def definition(self, default=None, **kwargs):
        """Generates code to define the C/C++ type."""
        if default == '""':
            default = '(char *) ""'

        return super().definition(default=default, **kwargs)


class BorrowedString(String):
    """Borrowed string type code generator."""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
    {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});
"""

    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result,
        }
        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class Char_and_Length(Type):
    """Character with length type code generator."""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
    {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});

    if(!{result:s}) {{
        goto on_error;
    }}
"""

    BUILDSTR = "s#"

    def __init__(self, name, data_type, length, length_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.data_type = data_type
        self.error_value = "return NULL;"
        self.interface = "char_and_length"
        self.length = length
        self.length_type = length_type
        self.name = name

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}, &{self.length:s}"

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return (
            f"({self.data_type:s}){self.name:s}, ({self.length_type:s}){self.length:s}"
        )

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        return f"{self.data_type:s} {self.name:s}, {self.length_type:s} {self.length:s}"

    def definition(self, default='""', **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return (
            f"    char *{self.name:s} = {default:s};\n"
            f"    Py_ssize_t {self.length:s} = strlen({default:s});\n"
        )

    def to_python_object(self, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"length": self.length, "name": self.name, "result": result}

        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class Integer(Type):
    """Signed integer type code generator."""

    BUILDSTR = "i"
    INT_TYPE = "int"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.interface = "integer"
        self.original_type = data_type
        self.type = self.INT_TYPE

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        return f"{self.original_type:s} {self.name:s} "

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        return (
            f"    PyErr_Clear();\n"
            f"    {destination:s} = PyLong_AsLongMask({source:s});\n"
        )

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        code = f"""\
    PyErr_Clear();
    {result:s} = PyLong_FromLong({name:s});
"""
        if sense == "proxied":
            code += (
                f"    if({result:s} == NULL) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
            )
        return code


class IntegerUnsigned(Integer):
    """Unsigned integer type code generator."""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
    {result:s} = PyList_New(0);
    for(array_index = 0; array_index < {array_size:s}; array_index++) {{
       PyList_Append({result:s}, PyLong_FromLong((long) {name:s}[array_index]));
    }}
"""

    BUILDSTR = "I"
    INT_TYPE = "unsigned int"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        return (
            f"    PyErr_Clear();\n"
            f"    {destination:s} = PyLong_AsUnsignedLongMask({source:s});\n"
        )

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        if "array_size" in self.additional_args:
            values_dict = {
                "name": name,
                "result": result,
                "array_size": self.additional_args["array_size"],
            }
            return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

        code = (
            f"    PyErr_Clear();\n"
            f"    {result:s} = PyLong_FromLong((long) {name:s});\n"
        )
        if sense == "proxied":
            code += (
                f"    if({result:s} == NULL) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
            )
        return code


class Integer8(Integer):
    """8-bit signed integer type code generator."""

    INT_TYPE = "int8_t"


class Integer8Unsigned(IntegerUnsigned):
    """8-bit unsigned integer type code generator."""

    INT_TYPE = "uint8_t"


class Integer16(Integer):
    """16-bit signed integer type code generator."""

    INT_TYPE = "int16_t"


class Integer16Unsigned(IntegerUnsigned):
    """16-bit unsigned integer type code generator."""

    INT_TYPE = "uint16_t"


class Integer32(Integer):
    """32-bit signed integer type code generator."""

    INT_TYPE = "int32_t"


class Integer32Unsigned(IntegerUnsigned):
    """32-bit unsigned integer type code generator."""

    INT_TYPE = "uint32_t"


class Integer64(Integer):
    """64-bit signed integer type code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
#if defined( HAVE_LONG_LONG )
    {destination:s} = PyLong_AsLongLongMask({source:s});
#else
    {destination:s} = PyLong_AsLongMask({source:s});
#endif
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
#if defined( HAVE_LONG_LONG )
    {result:s} = PyLong_FromLongLong({name:s});
#else
    {result:s} = PyLong_FromLong({name:s});
#endif
"""

    BUILDSTR = "L"
    INT_TYPE = "int64_t"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        values_dict = {"destination": destination, "source": source}

        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        code = self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

        if sense == "proxied":
            code += (
                f"    if({result:s} == NULL) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
            )
        return code


class Integer64Unsigned(Integer):
    """64-bit unsigned integer type code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
#if defined( HAVE_LONG_LONG )
    {destination:s} = PyLong_AsUnsignedLongLongMask({source:s});
#else
    {destination:s} = PyLong_AsUnsignedLongMask({source:s});
#endif
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
#if defined( HAVE_LONG_LONG )
    {result:s} = PyLong_FromUnsignedLongLong({name:s});
#else
    {result:s} = PyLong_FromUnsignedLong({name:s});
#endif
"""

    BUILDSTR = "K"
    INT_TYPE = "uint64_t"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        values_dict = {"destination": destination, "source": source}

        # TODO: use integer_object_copy_to_uint64 instead to support both long and int
        # objects.
        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        code = self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

        if sense == "proxied":
            code += (
                f"    if({result:s} == NULL) {{\n"
                f"        goto on_error;\n"
                f"    }}\n"
            )
        return code


class Long(Integer):
    """Long type code generator."""

    BUILDSTR = "l"
    INT_TYPE = "long"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        values_dict = {"destination": destination, "source": source}

        return (
            "PyErr_Clear();\n" "{destination:s} = PyLong_AsLongMask({source:s});\n"
        ).format(**values_dict)

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        code = f"PyErr_Clear();\n" f"{result:s} = PyLong_FromLongLong({name:s});\n"
        if sense == "proxied":
            code += f"if({result:s} == NULL) {{\n" f"    goto on_error;\n" f"}}\n"
        return code


class LongUnsigned(Integer):
    """Unsigned long type code generator."""

    BUILDSTR = "k"
    INT_TYPE = "unsigned long"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        return (
            f"PyErr_Clear();\n"
            f"{destination:s} = PyLong_AsUnsignedLongMask({source:s});\n"
        )

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        code = f"PyErr_Clear();\n" f"{result:s} = PyLong_FromUnsignedLong({name:s});\n"
        if sense == "proxied":
            code += f"if({result:s} == NULL) {{\n" f"    goto on_error;\n" f"}}\n"
        return code


class Char(Integer):
    """Character (char) type code generator."""

    _PRE_CALL_TEMPLATE = """\
    if(strlen(str_{name:s}) != 1) {
        PyErr_Format(PyExc_RuntimeError, "You must only provide a single character for arg {name:s}");
        goto on_error;
    }

    {name:s} = str_{name:s}[0];
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
{{
    char *str_{name:s} = &{name:s};

    PyErr_Clear();
    {result:s} = PyBytes_FromStringAndSize(str_{name:s}, 1);

    if(!{result:s}) {{
        goto on_error;
}}
"""

    BUILDSTR = "s"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.interface = "small_integer"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&str_{self.name:s}"

    def definition(self, default='"\\x0"', **unused_kwargs):
        """Generates code to define the C/C++ type."""
        # Silence unused warnings.
        return (
            f"char {self.name:s} UNUSED = 0;\n"
            f"char *str_{self.name:s} UNUSED = {default:s};\n"
        )

    def pre_call(self, method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        method.error_set = True

        values_dict = {"name": self.name}

        return self._PRE_CALL_TEMPLATE.format(**values_dict)

    # pylint: disable=arguments-differ
    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        # We really want to return a string here.
        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class StringOut(String):
    """Code generator that handles string pushed out through OUT."""

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.sense = "OUT"


class IntegerOut(Integer):
    """Code generator that handles integers pushed out through OUT int *result."""

    BUILDSTR = ""
    INT_TYPE = "int *"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.sense = "OUT_DONE"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return self.name

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return f"{self.name:s}"

    def definition(self, default=0, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        # We need to make static storage for the pointers
        storage = f"storage_{self.name:s}"
        bare_type = self.type.split()[0]
        type_definition = Type.definition(self, default=f"&{storage:s}")

        return f"""\
{bare_type:s} {storage:s} = 0;
{type_definition:s}
"""

    def passthru_call(self):
        """Returns how we should call the function when simply passing args directly"""
        return self.name

    def python_name(self):
        """Retrieves the Python name of the C/C++ type."""
        return None

    # pylint: disable=arguments-differ
    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        return f"PyErr_Clear();\n" f"{result:s} = PyLong_FromLongLong(*{name:s});\n"


class PInteger32UnsignedOut(IntegerOut):
    """Code generator that handles uint32_t* pushed out through OUT."""

    INT_TYPE = "uint32_t *"


class PInteger64UnsignedOut(IntegerOut):
    """Code generator that handles uint64_t* pushed out through OUT."""

    INT_TYPE = "uint64_t *"


class Char_and_Length_OUT(Char_and_Length):
    """Code generator that handles char* with length pushed out through OUT."""

    _PRE_CALL_TEMPLATE = """\
    PyErr_Clear();

    tmp_{name:s} = PyBytes_FromStringAndSize(NULL, {length:s});
    if(!tmp_{name:s}) {{
        goto on_error;
    }}

    PyBytes_AsStringAndSize(tmp_{name:s}, &{name:s}, (Py_ssize_t *)&{length:s});
"""

    _PYTHON_PROXY_POST_CALL_TEMPLATE = """\
{{
    char *tmp_buff = NULL;
    Py_ssize_t tmp_len = 0;

    if(PyBytes_AsStringAndSize({result:s}, &tmp_buff, &tmp_len) == -1) {{
        goto on_error;
    }}
    /* Bound the user-controlled return length to the buffer
     * size that libtsk requested; a Python override that
     * returns more bytes than asked for would otherwise
     * overflow the caller's buffer.
     */
    if((size_t) tmp_len > (size_t) {length:s}) {{
        tmp_len = (Py_ssize_t) {length:s};
    }}
    memcpy({name:s}, tmp_buff, tmp_len);
    Py_DecRef({result:s});
    {result:s} = PyLong_FromLong(tmp_len);
    if({result:s} == NULL) {{
        goto on_error;
    }}
}}
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    /* NOTE - this should never happen
     * it might indicate an overflow condition.
     */
    if(func_return > (uint64_t) {length:s}) {{
        printf("Programming Error - possible overflow!!\\n");
        abort();

    // Do we need to truncate the buffer for a short read?
    }} else if(func_return < (uint64_t) {length:s}) {{
        _PyBytes_Resize(&tmp_{name:s}, (Py_ssize_t) func_return);
    }}

    {result:s} = tmp_{name:s};
"""

    BUILDSTR = "l"

    def __init__(self, name, data_type, length, length_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, length, length_type, *args, **kwargs)
        self.sense = "OUT_DONE"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.length:s}"

    def definition(self, default=0, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return (
            f"    char *{self.name:s} = NULL;\n"
            f"    Py_ssize_t {self.length:s} = {default:d};\n"
            f"    PyObject *tmp_{self.name:s} = NULL;\n"
        )

    def error_cleanup(self):
        """Generates code for clean up after error for the C/C++ type."""
        return (
            f"    if(tmp_{self.name:s} != NULL) {{\n"
            f"        Py_DecRef(tmp_{self.name:s});\n"
            f"    }}\n"
        )

    def pre_call(self, unused_method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        values_dict = {"length": self.length, "name": self.name}

        return self._PRE_CALL_TEMPLATE.format(**values_dict)

    def python_name(self):
        """Retrieves the Python name of the C/C++ type."""
        return self.length

    def python_proxy_post_call(self, result="Py_result"):
        values_dict = {"length": self.length, "name": self.name, "result": result}

        return self._PYTHON_PROXY_POST_CALL_TEMPLATE.format(**values_dict)

    # pylint: disable=arguments-renamed
    def to_python_object(self, name=None, result="Py_result", sense="IN", **kwargs):
        """Generates code to a Python object into a C/C++ type."""
        if "results" in kwargs:
            kwargs["results"].pop(0)

        if sense == "proxied":
            return (
                f"py_{self.name:s} = PyLong_FromSize_t((size_t) {self.length:s});\n"
                f"if(py_{self.name:s} == NULL) {{\n"
                f"    goto on_error;\n"
                f"}}\n"
            )

        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result,
        }
        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class TDB_DATA_P(Char_and_Length_OUT):
    """Code generator that handles TBD_DATA pushed out through OUT."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
{destination:s} = talloc_zero(self, {bare_type:s});
{{
    char *buf = NULL;
    Py_ssize_t tmp = 0;

    PyErr_Clear();

    if(PyBytes_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{
        goto on_error;
    }}

    // Take a copy of the Python string
    {destination:s}->dptr = talloc_memdup({destination:s}, buf, tmp);
    {destination:s}->dsize = tmp;
}}
// We no longer need the Python object
Py_DecRef({source:s});
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
    {result:s} = PyBytes_FromStringAndSize((char *){name:s}->dptr, {name:s}->dsize);
    talloc_free({name:s});
"""

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"{self.name:s}.dptr, &{self.name:s}.dsize"

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return Type.call_arg(self)

    def definition(self, default=None, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return Type.definition(self)

    def from_python_object(self, source, destination, method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        method.error_set = True
        values_dict = {
            "bare_type": "TDB_DATA",
            "destination": destination,
            "source": source,
        }
        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def pre_call(self, unused_method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        return ""

    # pylint: disable=arguments-differ
    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class TDB_DATA(TDB_DATA_P):
    """TDB_DATA code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
{{
    char *buf = NULL;
    Py_ssize_t tmp = 0;

    PyErr_Clear();

    if(PyBytes_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{
        goto on_error;
    }}
    // Take a copy of the Python string - This leaks - how to fix it?
    {destination:s}.dptr = talloc_memdup(NULL, buf, tmp);
    {destination:s}.dsize = tmp;
}}
// We no longer need the Python object
Py_DecRef({source:s});
"""

    _TO_PYTHON_OBJECT_TEMPLATE = """\
    PyErr_Clear();
    {result:s} = PyBytes_FromStringAndSize((char *){name:s}.dptr, {name:s}.dsize);
"""

    def __init__(self, name, data_type, length, length_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, length, length_type, *args, **kwargs)
        self.error_value = "{result:s}.dptr = NULL;\nreturn {result:s};"

    def from_python_object(self, source, destination, method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        method.error_set = True
        values_dict = {"destination": destination, "source": source}

        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        return self._TO_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class Void(Type):
    """Void code generator."""

    BUILDSTR = ""

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.error_value = "return;"
        self.original_type = ""

    def assign(self, call, unused_method, target=None, **unused_kwargs):
        """Generates code to assign the C/C++ type."""
        # We don't assign the result to anything.
        return (
            f"    Py_BEGIN_ALLOW_THREADS\n"
            f"    (void) {call:s};\n"
            f"    Py_END_ALLOW_THREADS\n"
        )

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return None

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return "NULL"

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        return "void *ctx"

    def definition(self, default=None, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return ""

    def return_value(self, value):
        """Generates code of the C/C++ type as a return value."""
        return "return;"

    def to_python_object(self, **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        return "Py_IncRef(Py_None);\n" "Py_result = Py_None;\n"


class PVoid(Void):
    """Void pointer code generator."""


class StringArray(String):
    """String array code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
{{
    Py_ssize_t i = 0;
    Py_ssize_t size = 0;

    if({source:s}) {{
        if(!PySequence_Check({source:s})) {{
            PyErr_Format(PyExc_ValueError, "{destination:s} must be a sequence");
            goto on_error;
        }}
        size = PySequence_Size({source:s});
    }}
    {destination:s} = talloc_zero_array(NULL, char *, size + 1);

    for(i = 0; i < size; i++) {{
        PyObject *tmp = PySequence_GetItem({source:s}, i);
        if(!tmp) {{
            goto on_error;
        }}
        {destination:s}[i] = PyBytes_AsString(tmp);

        if(!{destination:s}[i]) {{
            Py_DecRef(tmp);
            goto on_error;
        }}
        Py_DecRef(tmp);
    }}
}}
"""

    BUILDSTR = "O"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.interface = "array"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&py_{self.name:s}"

    def definition(self, default='""', **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return (
            f"    char **{self.name:s} = NULL;\n"
            f"    PyObject *py_{self.name:s} = NULL;\n"
        )

    def error_condition(self):
        """Generates code to handle the C/C++ type in an error conditition."""
        return (
            f"    if({self.name:s}) {{\n"
            f"        talloc_free({self.name:s});\n"
            f"    }}\n"
        )

    def from_python_object(
        self, source, destination, method, context="NULL", **unused_kwargs
    ):
        """Generates code to convert a C/C++ type into a Python object."""
        method.error_set = True
        values_dict = {"destination": destination, "source": source}

        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def pre_call(self, method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        return self.from_python_object(f"py_{self.name:s}", self.name, method)


class Wrapper(Type):
    """Wrapped C type code generator."""

    _ASSIGN_BORROWED_ATTRIBUTES_TEMPLATE = """\
        #error unchecked BORROWED code segment
        {incref:s}(wrapped_{name:s}->base);
        if(((Object) wrapped_{name:s}->base)->extension) {{
            Py_IncRef((PyObject *) ((Object) wrapped_{name:s}->base)->extension);
        }}
"""

    _ASSIGN_START_TEMPLATE = """\
    {{
        Object returned_object = NULL;

        ClearError();

        Py_BEGIN_ALLOW_THREADS
        // This call will return a Python object if the base is a proxied Python object
        // or a talloc managed object otherwise.
        returned_object = (Object) {call:s};
        Py_END_ALLOW_THREADS

        if(check_error()) {{
            if(returned_object != NULL) {{
                if(self->base_is_python_object != 0) {{
                    Py_DecRef((PyObject *) returned_object);
                }} else if(self->base_is_internal != 0) {{
                    talloc_free(returned_object);
                }}
            }}
            goto on_error;
        }}
"""

    _ASSIGN_WRAPPER_TEMPLATE = """\
        wrapped_{name:s} = new_class_wrapper(returned_object, self->base_is_python_object, (PyObject *) self);

        if(wrapped_{name:s} == NULL) {{
            if(returned_object != NULL) {{
                if(self->base_is_python_object != 0) {{
                    Py_DecRef((PyObject *) returned_object);
                }} else if(self->base_is_internal != 0) {{
                    talloc_free(returned_object);
                }}
            }}
            goto on_error;
        }}
"""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
     /* First check that the returned value is in fact a Wrapper */
     if(!type_check({source:s}, &{type:s}_Type)) {{
          PyErr_Format(PyExc_RuntimeError, "function must return an {type:s} instance");
          goto on_error;
     }}

     {destination:s} = ({type:s}) ((Gen_wrapper) {source:s})->base;

     if(!{destination:s}) {{
          PyErr_Format(PyExc_RuntimeError, "{type:s} instance is no longer valid (was it gc\'ed?)");
          goto on_error;
}}

"""

    _PRE_CALL_TEMPLATE = """\
    if(wrapped_{name:s} == NULL || (PyObject *)wrapped_{name:s} == Py_None) {{
        {name:s} = NULL;
    }} else if(!type_check((PyObject *)wrapped_{name:s},&{original_type:s}_Type)) {{
        PyErr_Format(PyExc_RuntimeError, "{name:s} must be derived from type {original_type:s}");
        goto on_error;
    }} else if(wrapped_{name:s}->base == NULL) {{
        PyErr_Format(PyExc_RuntimeError, "{original_type:s} instance is no longer valid (was it gc\'ed?)");
        goto on_error;
    }} else {{
        {name:s} = ({type:s}) wrapped_{name:s}->base;
        if(self->python_object{python_object_index:d} == NULL) {{
            self->python_object{python_object_index:d} = (PyObject *) wrapped_{name:s};
            Py_IncRef(self->python_object{python_object_index:d});
        }}
    }}
"""

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.error_value = "return NULL;"
        self.original_type = None
        self.sense = "IN"

    def assign(self, call, method, target=None, **unused_kwargs):
        """Generates code to assign the C/C++ type."""
        method.error_set = True

        values_dict = {
            "call": call.strip(),
            "incref": INCREF,
            "name": target or self.name,
            "type": self.type,
        }
        result = self._ASSIGN_START_TEMPLATE.format(**values_dict)

        # Is NULL an acceptable return type? In some Python code NULL can be returned,
        # e.g. in iterators, but usually it should be converted to Py_None.
        if "NULL_OK" in self.attributes:
            result += (
                "        if(returned_object == NULL) {\n"
                "            goto on_error;\n"
                "        }\n"
            )

        # Pass the calling pyXxx wrapper as parent so the child holds a strong reference
        # back to it. Required for free-threaded safety: without this, another thread
        # could drop the parent's last visible reference and free the underlying libtsk
        # handle while this child is still in use.
        result += self._ASSIGN_WRAPPER_TEMPLATE.format(**values_dict)

        if "BORROWED" in self.attributes:
            result += self._ASSIGN_BORROWED_ATTRIBUTES_TEMPLATE.format(**values_dict)

        result += "    }\n"

        return result

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&wrapped_{self.name:s}"

    def call_arg(self):
        """Generates code to use the C/C++ type as an argument to a function call."""
        return f"{self.name:s}"

    def definition(self, default="NULL", sense="IN", **unused_kwargs):
        """Generates code to define the C/C++ type."""
        result = f"    Gen_wrapper wrapped_{self.name:s} UNUSED = {default:s};\n"
        if sense == "IN" and not "OUT" in self.attributes:
            result += f"    {self.type:s} UNUSED {self.name:s};\n"

        return result

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        values_dict = {"destination": destination, "source": source, "type": self.type}

        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)

    def pre_call(self, unused_method, python_object_index=1, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        if "OUT" in self.attributes or self.sense == "OUT":
            return ""

        self.original_type = self.type.split()[0]

        values_dict = {
            "name": self.name,
            "original_type": self.original_type,
            "python_object_index": python_object_index,
            "type": self.type,
        }
        return self._PRE_CALL_TEMPLATE.format(**values_dict)

    def returned_python_definition(self, default="NULL", **unused_kwargs):
        """Generates code to define the C/C++ type."""
        return f"{self.type:s} {self.name:s} = {default:s};\n"

    def to_python_object(
        self, name=None, result="Py_result", sense="IN", **unused_kwargs
    ):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        if sense == "proxied":
            # Proxied path: wrapping a libtsk struct produced inside a user-overridden
            # Python method. The caller's Python frame already holds the parent
            # reference, so no additional parent keepalive is needed here.
            return (
                f"{result:s} = (PyObject *) new_class_wrapper((Object){name:s}, 0, "
                f"NULL);\n"
            )

        return f"{result:s} = (PyObject *) wrapped_{name:s};\n"


class PointerWrapper(Wrapper):
    """Pointer a to wrapped C type code generator."""

    _PRE_CALL_TEMPLATE = """\
if(!wrapped_{name:s} || (PyObject *)wrapped_{name:s}==Py_None) {{
   {name:s} = NULL;
}} else if(!type_check((PyObject *)wrapped_{name:s},&{original_type:s}_Type)) {{
     PyErr_Format(PyExc_RuntimeError, "{name:s} must be derived from type {original_type:s}");
     goto on_error;
}} else {{
   {name:s} = ({original_type:s} *)&wrapped_{name:s}->base;
}};
"""

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        data_type = data_type.split()[0]
        super().__init__(name, data_type, *args, **kwargs)

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&wrapped_{self.name:s}"

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        return f"{self.type:s} *{self.name:s}"

    def definition(self, default="NULL", sense="IN", **unused_kwargs):
        """Generates code to define the C/C++ type."""
        result = f"    Gen_wrapper wrapped_{self.name:s} = {default:s};\n"
        if sense == "IN" and not "OUT" in self.attributes:
            result += f"    {self.type:s} *{self.name:s};\n"

        return result

    # pylint: disable=arguments-differ
    def pre_call(self, unused_method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        if "OUT" in self.attributes or self.sense == "OUT":
            return ""

        self.original_type = self.type.split()[0]
        values_dict = {"name": self.name, "original_type": self.original_type}

        return self._PRE_CALL_TEMPLATE.format(**values_dict)


class StructWrapper(Wrapper):
    """Wrapped C struct code generator."""

    _ASSIGN_START_TEMPLATE = """
        PyErr_Clear();

        /* GC_New (not PyObject_New) because the type carries
         * Py_TPFLAGS_HAVE_GC; GC_Track is deferred to after the
         * keepalive fields below are wired. */
        wrapped_{name:s} = (Gen_wrapper) PyObject_GC_New(py{type:s}, &{type:s}_Type);
        if(wrapped_{name:s} == NULL) {{
            return NULL;
        }}

"""

    active = False

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.original_type = data_type.split()[0]

    def assign(self, call, method, target=None, borrowed=True, **unused_kwargs):
        """Generates code to assign the C/C++ type."""
        self.original_type = self.type.split()[0]

        name = target or self.name

        values_dict = {
            "call": call.strip(),
            "name": name,
            "type": self.original_type,
        }
        result = self._ASSIGN_START_TEMPLATE.format(**values_dict)

        if borrowed:
            # The struct base points into memory owned by the parent
            # Python wrapper. Keep the parent alive via python_object1
            # so a different thread cannot free the underlying libtsk
            # handle while this borrowed wrapper is still in use.
            result += (
                "        // Base is borrowed from another object.\n"
                "        wrapped_{name:s}->base = {call:s};\n"
                "        wrapped_{name:s}->base_is_python_object = 0;\n"
                "        wrapped_{name:s}->base_is_internal = 0;\n"
                "        Py_IncRef((PyObject *) self);\n"
                "        wrapped_{name:s}->python_object1 = (PyObject *) self;\n"
                "        wrapped_{name:s}->python_object2 = NULL;\n"
                "\n"
            ).format(**values_dict)
        else:
            # Method-return path (borrowed=False is passed by the
            # method-call codegen). In practice every libtsk method
            # we wrap that returns a struct hands back a pointer into
            # parent-owned memory (e.g. tsk_vs_part_get returns a
            # TSK_VS_PART_INFO * inside the parent TSK_VS_INFO), and
            # the generated *_dealloc never frees self->base. So the
            # wrapper is logically *not* the owner; mark it as such
            # via base_is_internal = 0 to avoid misleading future code
            # that might gate a free/close on that flag. Keep the
            # parent alive via python_object1.
            result += (
                "        wrapped_{name:s}->base = {call:s};\n"
                "        wrapped_{name:s}->base_is_python_object = 0;\n"
                "        wrapped_{name:s}->base_is_internal = 0;\n"
                "        Py_IncRef((PyObject *) self);\n"
                "        wrapped_{name:s}->python_object1 = (PyObject *) self;\n"
                "        wrapped_{name:s}->python_object2 = NULL;\n"
                "\n"
            ).format(**values_dict)

        # All keepalive fields are wired; safe to expose to the GC.
        result += f"        PyObject_GC_Track((PyObject *) wrapped_{name:s});\n" f"\n"

        if "NULL_OK" in self.attributes:
            result += (
                "        if(wrapped_{name:s}->base == NULL) {{\n"
                "             Py_DecRef((PyObject *) wrapped_{name:s});\n"
                "             if(check_error()) {{\n"
                "                 goto on_error;\n"
                "             }}\n"
                "             return NULL;\n"
                "        }}\n"
            ).format(**values_dict)

        result += (
            "        // A NULL object gets translated to a None\n"
            "        if(wrapped_{name:s}->base == NULL) {{\n"
            "            Py_DecRef((PyObject *) wrapped_{name:s});\n"
            "            Py_IncRef(Py_None);\n"
            "            wrapped_{name:s} = (Gen_wrapper) Py_None;\n"
            "        }}\n"
        ).format(**values_dict)

        # TODO: with the following code commented out is makes no sense to have the
        # else clause here.

        #   "    }} else {{\n").format(**values_dict)

        # if "FOREIGN" in self.attributes:
        #     result += "// Not taking references to foreign memory\n"
        # elif "BORROWED" in self.attributes:
        #     result += (
        #         "talloc_reference({name:s}->ctx, {name:s}->base);\n"
        #     ).format(**values_dict)
        # else:
        #     result += (
        #         "talloc_steal({name:s}->ctx, {name:s}->base);\n"
        #     ).format(**values_dict)
        # result += "}}\n"

        return result

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}"

    def definition(self, default="NULL", sense="IN", **unused_kwargs):
        """Generates code to define the C/C++ type."""
        result = f"    Gen_wrapper wrapped_{self.name:s} = {default:s};\n"
        if sense == "IN" and not "OUT" in self.attributes:
            result += f"    {self.original_type:s} *{self.name:s} = NULL;\n"

        return result


class PointerStructWrapper(StructWrapper):
    """Pointer a to wrapped C struct code generator."""

    _FROM_PYTHON_OBJECT_TEMPLATE = """\
    if({source:s} == NULL || !type_check({source:s}, &{type:s}_Type)) {{
        PyErr_Format(PyExc_RuntimeError,
            "proxied {type:s} method returned NULL or wrong type");
        goto on_error;
    }}
    {destination:s} = ({type:s} *) ((Gen_wrapper) {source:s})->base;
"""

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&wrapped_{self.name:s}"

    def from_python_object(self, source, destination, unused_method, **unused_kwargs):
        """Generates code to convert a C/C++ type into a Python object."""
        values_dict = {
            "destination": destination,
            "source": source,
            "type": self.original_type,
        }
        return self._FROM_PYTHON_OBJECT_TEMPLATE.format(**values_dict)


class Timeval(Type):
    """struct timeval code generator."""

    BUILDSTR = "f"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.interface = "numeric"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}_flt"

    def definition(self, default=None, **kwargs):
        """Generates code to define the C/C++ type."""
        result = f"struct timeval {self.name:s};\n"
        result += self.local_definition(default=default, **kwargs)
        return result

    def local_definition(self, **unused_kwargs):
        """Generates code to local define the C/C++ type."""
        return f"float {self.name:s}_flt;\n"

    def pre_call(self, unused_method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        return (
            f"{self.name:s}.tv_sec = (int){self.name:s}_flt;\n"
            f"{self.name:s}.tv_usec = ({self.name:s}_flt - {self.name:s}.tv_sec) "
            f"* 1e6;\n"
        )

    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        values_dict = {"name": name or self.name, "result": result}

        return (
            "{name:s}_flt = (double)({name:s}.tv_sec) + {name:s}.tv_usec;\n"
            "{result:s} = PyFloat_FromDouble({name:s}_flt);\n"
        ).format(**values_dict)


class PyObject(Type):
    """Python object code generator."""

    BUILDSTR = "O"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.default = None
        self.interface = "opaque"

    def byref(self):
        """Generates code to reference the C/C++ type."""
        return f"&{self.name:s}"

    def definition(self, default="NULL", **unused_kwargs):
        """Generates code to define the C/C++ type."""
        self.default = default
        return f"PyObject *{self.name:s} = {self.default:s};\n"


class ResultException(BaseCodeGenerator):
    """Result exception code generator."""

    value = 0
    exception = "PyExc_IOError"

    def __init__(self, check, exception, message):
        """Initializes the code generator."""
        super().__init__()
        self.check = check
        self.exception = exception
        self.message = message

    def write(self, out):
        """Generates code of the C/C++ type."""
        out.write(
            f"\n"
            f"/* Handle exceptions */\n"
            f"if({self.check:s}) {{\n"
            f"    PyErr_Format(PyExc_{self.exception:s}, {self.message:s});\n"
            f"    goto on_error;\n"
            f"}}\n"
            f"\n"
        )


class Method(BaseCodeGenerator):
    """Method code generator."""

    _DEFINITION_BASE_GUARD_TEMPLATE = """
    // Make sure that we have something valid to wrap
    if(self->base == NULL) {{
        return PyErr_Format(PyExc_RuntimeError, "{class_name:s} object no longer valid");
    }}

"""

    _DEFINITION_PRECALL_TEMPLATE = """\
    // Check the function is implemented
    {{
        void *method = (void *) (({def_class_name:s}) self->base)->{method:s};

        if(method == NULL || (void *) unimplemented == (void *) method) {{
            PyErr_Format(PyExc_RuntimeError, "{class_name:s}.{method:s} is not implemented");
            goto on_error;
        }}

        // Make the call
        ClearError();
"""

    default_re = re.compile(r"DEFAULT\(([A-Z_a-z0-9]+)\) =(.+);")
    exception_re = re.compile(r"RAISES\(([^,]+),\s*([^\)]+)\) =(.+);")
    typedefed_re = re.compile(r"struct (.+)_t \*")

    def __init__(
        self, class_name, base_class_name, name, args, return_type, myclass=None
    ):
        """Initializes the code generator."""
        if not isinstance(myclass, ClassGenerator):
            raise RuntimeError("myclass not an instance of ClassGenerator")

        super().__init__()
        self.args = []
        self.base_class_name = base_class_name
        self.class_name = class_name
        self.defaults = {}
        self.definition_class_name = class_name
        self.docstring = ""
        self.error_set = False
        self.exception = None
        self.myclass = myclass
        self.name = name

        for arg_type, arg_name in args:
            self.add_arg(arg_type, arg_name)

        try:
            self.return_type = TypeDispatcher.dispatch("func_return", return_type)
            self.return_type.attributes.add("OUT")
            self.return_type.original_type = return_type
        except KeyError:
            # Is it a wrapped type?
            if return_type:
                self.log(
                    f"Unable to handle return type {self.class_name:s}.{self.name:s} "
                    f"{return_type:s}"
                )
            self.return_type = PVoid("func_return", "void *")

    def _prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        out.write(
            f"static PyObject *py{self.class_name:s}_{self.name:s}("
            f"py{self.class_name:s} *self, PyObject *args, PyObject *kwds)"
        )

    def add_arg(self, data_type, name):
        """Add an argument."""
        try:
            code_generator = TypeDispatcher.get_code_generator(name, data_type)
        except KeyError:
            # Sometimes types must be typedefed in advance.
            try:
                match = self.typedefed_re.match(data_type)

                original_type = match.group(0)
                data_type = match.group(1)
                self.log(f"Trying {data_type:s} for {original_type:s}")

                code_generator = TypeDispatcher.get_code_generator(name, data_type)

            except (AttributeError, KeyError):
                self.log(
                    f"Unable to handle type {self.class_name:s}.{self.name:s} "
                    f"{data_type:s}"
                )
                return

        # Here we collapse char * + int type interfaces into a coherent string like
        # interface.
        try:
            previous = self.args[-1]
            if code_generator.interface == "integer" and previous.interface == "string":

                # We make a distinction between IN variables and OUT variables.
                if previous.sense == "OUT":
                    cls = Char_and_Length_OUT
                else:
                    cls = Char_and_Length

                cls = cls(previous.name, previous.type, name, data_type)

                self.args[-1] = cls

                return
        except IndexError:
            pass

        self.args.append(code_generator)

    def clone(self, new_class_name):
        """Clone the code generator."""
        self.find_optional_vars()

        result = self.__class__(
            new_class_name,
            self.base_class_name,
            self.name,
            [],
            "void *",
            myclass=self.myclass,
        )
        result.args = self.args
        result.return_type = self.return_type
        result.definition_class_name = self.definition_class_name
        result.defaults = self.defaults
        result.exception = self.exception

        return result

    def comment(self):
        """Generates code with a comment about the C/C++ type."""
        args = []
        for argument in self.args:
            args.append(argument.comment())

        args_string = ", ".join(args)

        return (
            f"{self.return_type.original_type:s} {self.class_name:s}.{self.name:s}("
            f"{args_string:s});\n"
        )

    def error_condition(self):
        """Generates code to handle the C/C++ type in an error conditition."""
        result = ""
        if "DESTRUCTOR" in self.return_type.attributes:
            result += "self->base = NULL;\n"

        # If a Python wrapper was already allocated but check_error() fired
        # in the postcall, it must be released to avoid a refcount leak.
        if isinstance(
            self.return_type,
            (StructWrapper, PointerStructWrapper, Wrapper, PointerWrapper),
        ):
            name = self.return_type.name
            result += (
                f"    if(wrapped_{name:s} != NULL) {{\n"
                f"        Py_DecRef((PyObject *) wrapped_{name:s});\n"
                f"    }}\n"
            )

        if hasattr(self, "args"):
            for argument in self.args:
                if hasattr(argument, "error_cleanup"):
                    result += argument.error_cleanup()

        result += "    return NULL;\n"
        return result

    def find_optional_vars(self):
        """Find optional variables."""
        for line in self.docstring.splitlines():
            m = self.default_re.search(line)
            if m:
                name = m.group(1)
                value = m.group(2)

                self.log(f"Setting default value for {name:s} of {value:s}")
                self.defaults[name] = value.strip()

            m = self.exception_re.search(line)
            if m:
                self.exception = ResultException(m.group(1), m.group(2), m.group(3))

    def get_string(self):
        """Retrieves a string representation."""
        args = " , ".join([argument.get_string() for argument in self.args])
        return_type = self.return_type.get_string()
        return f"def {return_type:s} {self.name:s}({args:s}):"

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        self._prototype(out)
        out.write(";\n")

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        comment = self.comment()
        out.write(
            f"\n"
            f"/********************************************************\n"
            f"Autogenerated wrapper for function:\n"
            f"{comment:s}"
            f"********************************************************/\n"
        )
        self._prototype(out)

        return_type_class_name = self.return_type.__class__.__name__
        out.write(
            f"{{\n"
            f"    PyObject *returned_result = NULL;\n"
            f"    PyObject *Py_result = NULL;\n"
            f"\n"
            f"    // DEBUG: return type: {return_type_class_name:s}\n"
            f"    "
        )
        out.write(self.return_type.definition())

        self.write_local_vars(out)

        values_dict = {"class_name": self.class_name, "method": self.name}

        out.write(self._DEFINITION_BASE_GUARD_TEMPLATE.format(**values_dict))

        # Precall preparations
        out.write("    // Precall preparations\n")
        out.write(self.return_type.pre_call(self))
        for argument in self.args:
            out.write(argument.pre_call(self))

        values_dict = {
            "class_name": self.class_name,
            "def_class_name": self.definition_class_name,
            "method": self.name,
        }
        out.write(self._DEFINITION_PRECALL_TEMPLATE.format(**values_dict))

        base = f"(({self.definition_class_name:s}) self->base)"
        call = f"        {base:s}->{self.name:s}({base:s}"
        tmp = ""

        for argument in self.args:
            call_arg = argument.call_arg()
            if isinstance(argument, EnumType):
                tmp += f", ({argument.type:s}) {call_arg:s}"
            else:
                tmp += f", {call_arg:s}"

        call += f"{tmp:s})"

        # Now call the wrapped function
        out.write(self.return_type.assign(call, self, borrowed=False))
        if self.exception:
            self.exception.write(out)

        self.error_set = True

        out.write("""\
    };

    // Postcall preparations
""")
        # Postcall preparations
        post_calls = []

        post_call = self.return_type.post_call(self)
        post_calls.append(post_call)
        out.write(f"    {post_call:s}")

        for argument in self.args:
            post_call = argument.post_call(self)
            if post_call not in post_calls:
                post_calls.append(post_call)
                out.write(f"    {post_call:s}")

        # Now assemble the results
        results = [self.return_type.to_python_object()]
        for argument in self.args:
            if argument.sense == "OUT_DONE":
                # TODO: to_python_object has no results kwarg
                code = argument.to_python_object(results=results)
                results.append(code)

        # If all the results are returned by reference we dont need
        # to prepend the void return value at all.
        if isinstance(self.return_type, Void) and len(results) > 1:
            results.pop(0)

        out.write("\n    // prepare results\n")
        # Make a tuple of results and pass them back
        if len(results) > 1:
            out.write("returned_result = PyList_New(0);\n")
            for result in results:
                out.write(result)
                out.write(
                    "PyList_Append(returned_result, Py_result);\n"
                    "Py_DecRef(Py_result);\n"
                )
            out.write("return returned_result;\n")
        else:
            out.write(results[0])
            # This useless code removes compiler warnings
            out.write("""\
    returned_result = Py_result;
    return returned_result;
""")

        # Write the error part of the function
        if self.error_set:
            out.write("\non_error:\n")
            out.write(self.error_condition())

        out.write("};\n\n")

    def write_local_vars(self, out):
        """Generates code of local variables of the C/C++ type."""
        self.find_optional_vars()

        # We do it in two passes - first mandatory then optional
        kwlist = "    const char *kwlist[] = {"
        # Mandatory
        for argument in self.args:
            python_name = argument.python_name()
            if python_name and python_name not in self.defaults:
                kwlist += f'"{python_name:s}", '

        for argument in self.args:
            python_name = argument.python_name()
            if python_name and python_name in self.defaults:
                kwlist += f'"{python_name:s}", '

        kwlist += " NULL};\n"

        for argument in self.args:
            out.write(
                f"    // DEBUG: local arg type: {argument.__class__.__name__:s}\n"
            )
            python_name = argument.python_name()

            try:
                out.write(argument.definition(default=self.defaults[python_name]))
            except KeyError:
                out.write(argument.definition())

        # Make up the format string for the parse args in two pases
        parse_line = ""
        for argument in self.args:
            python_name = argument.python_name()
            if argument.BUILDSTR and python_name not in self.defaults:
                parse_line += argument.BUILDSTR

        optional_args = ""
        for argument in self.args:
            python_name = argument.python_name()
            if argument.BUILDSTR and python_name in self.defaults:
                optional_args += argument.BUILDSTR

        if optional_args:
            parse_line += "|" + optional_args

        # Iterators have a different prototype and do not need to unpack any args.
        if not "iternext" in self.name:
            # Now parse the args from Python objects.
            out.write("\n")
            out.write(kwlist)
            out.write(
                f"\n"
                f'    if(!PyArg_ParseTupleAndKeywords(args, kwds, "{parse_line:s}", '
            )
            tmp = ["(char **) kwlist"]
            for argument in self.args:
                ref = argument.byref()
                if ref:
                    tmp.append(ref)

            out.write(", ".join(tmp))
            self.error_set = True
            out.write("""\
)) {
        goto on_error;
    }
""")

    def PyMethodDef(self, out):
        """Generates code of PyMethodDef for the C/C++ type."""
        docstring = self.comment() + "\n\n" + self.docstring.strip()
        values_dict = {
            "class_name": self.class_name,
            "docstring": self.format_as_docstring(docstring),
            "name": self.name,
        }

        out.write(
            (
                '    {{ "{name:s}",\n'
                "      (PyCFunction) py{class_name:s}_{name:s},\n"
                "      METH_VARARGS|METH_KEYWORDS,\n"
                '      "{docstring:s}" }},\n'
                "\n"
            ).format(**values_dict)
        )


class IteratorMethod(Method):
    """Method that implements an iterator code generator."""

    def __init__(self, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(*args, **kwargs)

        # Tell the return type that a NULL Python return is ok
        self.return_type.attributes.add("NULL_OK")

    def _prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        method_name = f"py{self.class_name:s}_{self.name:s}"
        out.write(f"static PyObject *{method_name:s}(py{self.class_name:s} *self)")

    def get_string(self):
        """Retrieves a string representation."""
        return_type = self.return_type.get_string()
        return f"Iterator returning {return_type:s}."

    def PyMethodDef(self, out):
        """Generates code of PyMethodDef for the C/C++ type."""
        # This method should not go in the method table as its linked in directly.


class SelfIteratorMethod(IteratorMethod):
    """Method that implements a self iterator code generator."""

    _DEFINITION_TEMPLATE = """\
{{
    if(self->base == NULL) {{
        return PyErr_Format(PyExc_RuntimeError,
            "{class_name:s}.{method:s}: object is not bound to any libtsk handle");
    }}
    (({class_name:s}) self->base)->{method:s}(({class_name:s}) self->base);
    return PyObject_SelfIter((PyObject *) self);
}}
"""

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        comment = self.comment()
        out.write(
            f"\n"
            f"/********************************************************\n"
            f" * Autogenerated wrapper for function:\n"
            f"{comment:s}"
            f"********************************************************/\n"
        )
        self._prototype(out)

        values_dict = {"class_name": self.class_name, "method": self.name}

        out.write(self._DEFINITION_TEMPLATE.format(**values_dict))


class ConstructorMethod(Method):
    """Constructor method code generator."""

    _DEFINITION_END_TEMPLATE = """\
);
    Py_END_ALLOW_THREADS

    if(!CheckError(EZero)) {{
        char *buffer = NULL;
        PyObject *exception = resolve_exception(&buffer);

        PyErr_Format(exception, "%s", buffer);
        ClearError();
        goto on_error;
    }}
    if(result_constructor == NULL) {{
        PyErr_Format(PyExc_IOError, "Unable to construct class {class_name:s}");
        goto on_error;
    }}

    /* Track only after every PyObject* field is wired. The
     * IsTracked guard makes re-init (a second __init__) a no-op. */
    if(!PyObject_GC_IsTracked((PyObject *) self)) {{
        PyObject_GC_Track((PyObject *) self);
    }}
    return 0;
"""

    _DEFINITION_ERROR_TEMPLATE = """
on_error:
    if(self->python_object2 != NULL) {{
        Py_DecRef(self->python_object2);
        self->python_object2 = NULL;
    }}
    if(self->python_object1 != NULL) {{
        Py_DecRef(self->python_object1);
        self->python_object1 = NULL;
    }}
    if(self->base != NULL) {{
        talloc_free(self->base);
        self->base = NULL;
    }}
{error_condition:s}
"""

    _DEFINITION_INIALIZE_PROXIES_TEMPLATE = """\
    /* Release any state from a prior __init__ call so that
     * re-initialization does not leak keepalives or libtsk handles.
     */
    Py_CLEAR(self->python_object1);
    Py_CLEAR(self->python_object2);
    if(self->base != NULL) {{
        if(self->base_is_python_object != 0) {{
            Py_DecRef((PyObject *) self->base);
        }} else if(self->base_is_internal != 0) {{
            talloc_free(self->base);
        }}
        self->base = NULL;
    }}

    /* Initialise is used to keep a reference on the object?
     * If not called no longer valid warnings have been seen
     * on Windows.
     */
    self->initialise = (function_initialize_Gen_wrapper_t) py{class_name:s}_initialize_proxies;

"""

    _DEFINITION_WRAPPED_FUNCTION_TEMPLATE = """\
    ClearError();

    /* Allocate a new instance */
    self->base = ({class_name:s}) alloc_{class_name:s}();
    if(self->base == NULL) {{
        PyErr_NoMemory();
        goto on_error;
    }}
    self->base_is_python_object = 0;
    self->base_is_internal = 1;
    self->object_is_proxied = 0;

    /* Update the target by replacing its methods with proxies
     * to call back into Python
     */
    py{class_name:s}_initialize_proxies(self, self->base);

    /* Now call the constructor */
    Py_BEGIN_ALLOW_THREADS
"""

    _DESTRUCTOR_TEMPLATE = """\
static void {class_name:s}_dealloc(py{class_name:s} *self) {{
    struct _typeobject *ob_type = NULL;

    if(self != NULL) {{
        /* UnTrack first: dealloc tears down PyObject* fields
         * the GC traverse function reads. */
        PyObject_GC_UnTrack((PyObject *) self);
        if(self->base != NULL) {{
            if(self->base_is_python_object != 0) {{
                Py_DecRef((PyObject*) self->base);
            }} else if(self->base_is_internal != 0) {{
                {free:s}(self->base);
            }}
            self->base = NULL;
        }}
        if(self->python_object2 != NULL) {{
            Py_DecRef(self->python_object2);
            self->python_object2 = NULL;
        }}
        if(self->python_object1 != NULL) {{
            Py_DecRef(self->python_object1);
            self->python_object1 = NULL;
        }}
        ob_type = Py_TYPE(self);
        if(ob_type != NULL && ob_type->tp_free != NULL) {{
            ob_type->tp_free((PyObject*) self);
        }}
    }}
}}

"""

    _INITIALIZE_PROXIES_TEMPLATE = """\
static void py{class_name:s}_initialize_proxies(py{class_name:s} *self, void *item) {{
    {class_name:s} target = ({class_name:s}) item;

    /* Maintain a reference to the Python object
     * in the C object extension
     */
    ((Object) item)->extension = self;

"""

    _INITIALIZE_PROXIES_METHOD_TEMPLATE = """\
    if(check_method_override((PyObject *) self, &{class_name:s}_Type, "{name:s}")) {{
        // Proxy the {name:s} method
        (({definition_class_name:s}) target)->{name:s} = {proxied_name:s};
    }}
"""

    def _prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        out.write(
            f"static int py{self.class_name:s}_init(py{self.class_name:s} *self, "
            f"PyObject *args, PyObject *kwds)\n"
        )

    def error_condition(self):
        """Generates code to handle the C/C++ type in an error conditition."""
        return "    return -1;"

    def initialize_proxies(self, out):
        """Generates code to initialize proxies for the C/C++ type."""
        self.myclass.module.function_definitions.add(
            f"py{self.class_name:s}_initialize_proxies"
        )
        values_dict = {"class_name": self.class_name}

        out.write(self._INITIALIZE_PROXIES_TEMPLATE.format(**values_dict))

        # Install proxies for all the method in the current class.
        for method in self.myclass.module.classes[self.class_name].methods:
            if method.name.startswith("_"):
                continue

            # Since the SleuthKit uses close method also for freeing it needs
            # to be handled separately to prevent the C/C++ code calling back
            # into a garbage collected Python object. For close we keep the
            # default implementation and have its destructor deal with
            # correctly closing the SleuthKit object.
            if method.name != "close":
                values_dict = {
                    "class_name": method.class_name,
                    "definition_class_name": method.definition_class_name,
                    "name": method.name,
                    "proxied_name": method.proxied.get_name(),
                }
                out.write(
                    self._INITIALIZE_PROXIES_METHOD_TEMPLATE.format(**values_dict)
                )

        out.write("}\n\n")

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        self._prototype(out)

        out.write(
            f";\n"
            f"static void py{self.class_name:s}_initialize_proxies("
            f"py{self.class_name:s} *self, void *item);\n"
        )

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        self.initialize_proxies(out)
        self._prototype(out)

        out.write(f"{{\n" f"    {self.class_name:s} result_constructor = NULL;\n")
        self.write_local_vars(out)

        # Assign the initialize_proxies handler
        values_dict = {
            "class_name": self.class_name,
            "definition_class_name": self.definition_class_name,
        }
        out.write(self._DEFINITION_INIALIZE_PROXIES_TEMPLATE.format(**values_dict))

        # Precall preparations
        python_object_index = 1
        for argument in self.args:
            out.write(argument.pre_call(self, python_object_index=python_object_index))
            python_object_index += 1

        # Now call the wrapped function
        out.write(self._DEFINITION_WRAPPED_FUNCTION_TEMPLATE.format(**values_dict))

        out.write(
            f"    result_constructor = CONSTRUCT_INITIALIZE({self.class_name:s}, "
            f"{self.definition_class_name:s}, Con, self->base"
        )
        tmp = ""
        for argument in self.args:
            call_arg = argument.call_arg()
            if isinstance(argument, EnumType):
                tmp += f", ({argument.type:s}) {call_arg:s}"
            else:
                tmp += f", {call_arg:s}"

        self.error_set = True
        out.write(tmp)

        out.write(self._DEFINITION_END_TEMPLATE.format(**values_dict))

        # Write the error part of the function.
        if self.error_set:
            values_dict = {"error_condition": self.error_condition()}
            out.write(self._DEFINITION_ERROR_TEMPLATE.format(**values_dict))

        out.write("}\n\n")

    def write_destructor(self, out):
        """Generates code of a destructor of the C/C++ type."""
        values_dict = {"class_name": self.class_name, "free": FREE}

        out.write(self._DESTRUCTOR_TEMPLATE.format(**values_dict))


class GetattrMethod(Method):
    """Getattr method code generator."""

    _BUILT_INS_ATTRIBUTE_TEMPLATE = """
        string_object = PyUnicode_FromString("{name:s}");
        if(string_object == NULL) {{
            Py_DecRef(list_object);
            goto on_error;
        }}
        if(PyList_Append(list_object, string_object) < 0) {{
            Py_DecRef(string_object);
            Py_DecRef(list_object);
            goto on_error;
        }}
        Py_DecRef(string_object);
"""

    # TODO: remove additional empty line, currently kept for refactoring.
    _BUILT_INS_METHODS_TEMPLATE = """

        for(i = {class_name:s}_methods; i->ml_name; i++) {{
            string_object = PyUnicode_FromString(i->ml_name);
            if(string_object == NULL) {{
                Py_DecRef(list_object);
                goto on_error;
            }}
            if(PyList_Append(list_object, string_object) < 0) {{
                Py_DecRef(string_object);
                Py_DecRef(list_object);
                goto on_error;
            }}
            Py_DecRef(string_object);
        }}
        if( utf8_string_object != NULL ) {{
            Py_DecRef(utf8_string_object);
        }}
        return list_object;
    }}
"""

    _BUILT_INS_START_TEMPLATE = """\
    if(strcmp(name, "__members__") == 0) {
        PyMethodDef *i = NULL;
        PyObject *list_object = NULL;
        PyObject *string_object = NULL;

        list_object = PyList_New(0);
        if(list_object == NULL) {
            goto on_error;
        }
"""

    _DEFINITION_GETTERS_TEMPLATE = """\
PyObject *py{class_name:s}_{name:s}_getter(py{class_name:s} *self, PyObject *arguments) {{
    PyObject *Py_result = NULL;
{python_def:s}

    if(self->base == NULL) {{
        return PyErr_Format(PyExc_RuntimeError,
            "{class_name:s}.{name:s}: object is not bound "
            "to any libtsk handle (was it instantiated "
            "directly?)");
    }}

{python_assign:s}
{python_obj:s}

    return Py_result;

"""

    _DEFINITION_START_TEMPLATE = """\
static PyObject *py{class_name:s}_getattr(py{class_name:s} *self, PyObject *pyname) {{
    PyObject *result = NULL;
    char *name = NULL;

    PyObject *utf8_string_object  = NULL;

    // Try to hand it off to the Python native handler first
    result = PyObject_GenericGetAttr((PyObject*) self, pyname);

    if(result) {{
        return result;
    }}

    PyErr_Clear();
    // No - nothing interesting was found by python
    utf8_string_object = PyUnicode_AsUTF8String(pyname);

    if(utf8_string_object != NULL) {{
        name = PyBytes_AsString(utf8_string_object);
    }}

    if(!self->base) {{
        if( utf8_string_object != NULL ) {{
            Py_DecRef(utf8_string_object);
        }}
        return PyErr_Format(PyExc_RuntimeError, "Wrapped object ({class_name:s}.{name:s}) no longer valid");
    }}
    if(!name) {{
        goto on_error;
    }}
"""

    def __init__(self, class_name, base_class_name, myclass):
        """Initializes the code generator."""
        super().__init__(class_name, base_class_name, "", [], "void", myclass=myclass)
        self._attributes = []
        self.error_set = True

        self.rename_class_name(class_name)

    def add_attribute(self, attr):
        """Add an attribute and register it with the type dispatcher."""
        if attr.name:
            self._attributes.append([self.class_name, attr])

    def built_ins(self, out):
        """Check if there are built-in attributes we need to support."""
        out.write(self._BUILT_INS_START_TEMPLATE)

        for _, attr in self.get_attributes():
            values_dict = {"name": attr.name}
            out.write(self._BUILT_INS_ATTRIBUTE_TEMPLATE.format(**values_dict))

        values_dict = {"class_name": self.class_name}
        out.write(self._BUILT_INS_METHODS_TEMPLATE.format(**values_dict))

    def clone(self, new_class_name):
        """Clone the code generator."""
        result = self.__class__(new_class_name, self.base_class_name, self.myclass)

        # pylint: disable=protected-access
        result._attributes = self._attributes[:]

        return result

    def get_attributes(self):
        """Retrieves the attributes."""
        for class_name, attr in self._attributes:
            if (
                not TypeDispatcher.is_active(attr.type)
                and not attr.type in self.myclass.module.active_structs
            ):
                continue

            yield class_name, attr

    def get_string(self):
        """Retrieves a string representation."""
        result = ""
        for _, attr in self.get_attributes():
            attr_string = attr.get_string()
            result += f"    {attr_string:s}\n"

        return result

    def rename_class_name(self, new_name):
        """This allows us to rename the class_name at a later stage.
        Required for late initialization of Structs whose name is not
        know until much later on.
        """
        # TODO fix this behavior, new_name can be None but it is unclear what the
        # behaviour should be. Python 3 requires the values to be set to string types.
        if not new_name:
            self.class_name = ""
            self.name = ""
        else:
            self.class_name = new_name
            self.name = f"py{new_name:s}_getattr"

        for attribure in self._attributes:
            attribure[0] = new_name

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        if not self.name:
            return

        # Define getattr.
        out.write(
            f"static PyObject *{self.name:s}(py{self.class_name:s} *self, "
            f"PyObject *name);\n"
        )
        # Define getters.
        for _, attr in self.get_attributes():
            out.write(
                f"PyObject *py{self.class_name:s}_{attr.name:s}_getter("
                f"py{self.class_name:s} *self, PyObject *arguments);\n"
            )

    def PyGetSetDef(self, out):
        """Generates code of PyGetSetDef for the C/C++ type."""
        for _, attr in self.get_attributes():
            # TODO: improve docstring.
            docstring = f"{attr.name:s}."
            values_dict = {
                "class_name": self.class_name,
                "docstring": self.format_as_docstring(docstring),
                "name": attr.name,
            }
            out.write(
                (
                    '    {{ "{name:s}",\n'
                    "      (getter) py{class_name:s}_{name:s}_getter,\n"
                    "      (setter) 0,\n"
                    '      "{docstring:s}",\n'
                    "      NULL }},\n"
                    "\n"
                ).format(**values_dict)
            )

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        if not self.name:
            return

        values_dict = {"class_name": self.class_name, "name": self.name}

        out.write(self._DEFINITION_START_TEMPLATE.format(**values_dict))

        self.built_ins(out)

        out.write(
            "\n"
            "    if( utf8_string_object != NULL ) {{\n"
            "        Py_DecRef(utf8_string_object);\n"
            "    }}\n"
            "    return PyObject_GenericGetAttr((PyObject *) self, pyname);\n"
        )
        # Write the error part of the function.
        if self.error_set:
            out.write(
                "on_error:\n"
                "    if( utf8_string_object != NULL ) {{\n"
                "        Py_DecRef(utf8_string_object);\n"
                "    }}\n" + self.error_condition()
            )

        out.write("}\n\n")

        self.write_definition_getters(out)

    def write_definition_getters(self, out):
        """Generates code to define getter methods of the C/C++ type."""
        for _, attr in self.get_attributes():
            if self.base_class_name:
                call = f"((({self.class_name:s}) self->base)->{attr.name:s})"
            else:
                call = f"(self->base->{attr.name:s})"

            values_dict = {
                "class_name": self.class_name,
                "name": attr.name,
                "python_obj": attr.to_python_object(),
                "python_assign": attr.assign(call, self, borrowed=True),
                "python_def": attr.definition(sense="OUT"),
            }
            out.write(self._DEFINITION_GETTERS_TEMPLATE.format(**values_dict))

            # Work-around for the String class that generates code that contains
            # "goto on_error".
            if isinstance(attr, String):
                out.write(f"on_error:\n    {attr.error_value:s}\n")

            out.write("}\n\n")


class ProxiedMethod(Method):
    """Proxied method code generator."""

    _DEFINITION_CRITICAL_SECTION_TEMPLATE = """\
    if(Py_result != NULL) {
        PyObject *extension = (PyObject *) ((Object) self)->extension;
        PyObject *old = NULL;
#if PY_VERSION_HEX >= 0x030D0000
        Py_BEGIN_CRITICAL_SECTION(extension);
#endif
        old = ((Gen_wrapper) extension)->python_object2;
        ((Gen_wrapper) extension)->python_object2 = Py_result;
#if PY_VERSION_HEX >= 0x030D0000
        Py_END_CRITICAL_SECTION();
#endif
        if(old != NULL) Py_DecRef(old);
        Py_result = NULL;
    }
    Py_DecRef(method_name);

"""

    _DEFINITION_GIL_ENSURE_TEMPLATE = """
    // Grab the GIL so we can do Python stuff
    gil_state = PyGILState_Ensure();

    method_name = PyUnicode_FromString("{name:s}");
    /* PyUnicode_FromString sets MemoryError on failure;
     * propagate via the proxied error machinery rather than
     * passing NULL to PyObject_CallMethodObjArgs (which would
     * raise SystemError and lose the original cause).
     */
    if(method_name == NULL) {{
        pytsk_fetch_error();
        goto on_error;
    }}

// Obtain Python objects for all the args:
"""

    _DEFINITION_METHODS_TEMPLATE = """\
    if(((Object) self)->extension == NULL) {{
        RaiseError(ERuntimeError, "No proxied object in {class_name:s}");
        goto on_error;
    }}

    // Now call the method
"""

    _DEFINITION_START_TEMPLATE = """\
 {
    PyGILState_STATE gil_state;
    PyObject *Py_result = NULL;
    PyObject *method_name = NULL;
"""

    def __init__(self, method, myclass):
        """Initializes the code generator."""
        super().__init__(
            method.class_name,
            method.base_class_name,
            method.name,
            [],
            "void",
            myclass=myclass,
        )
        self.args = method.args
        self.definition_class_name = method.definition_class_name
        self.docstring = f"Proxy for {method.name:s}"
        self.method = method
        self.myclass = myclass
        self.return_type = method.return_type

    def _prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        return_type = self.return_type.type.strip()
        name = self.get_name()
        class_name = self.definition_class_name
        out.write(f"static {return_type:s} {name:s}({class_name:s} self")

        for argument in self.args:
            tmp = argument.comment().strip()
            if tmp:
                out.write(f", {tmp:s}")

        out.write(")")

    def _write_definition(self, out):
        """Generates code to define the C/C++ type."""
        out.write(self._DEFINITION_START_TEMPLATE)
        out.write(self.return_type.returned_python_definition())

        for argument in self.args:
            out.write(argument.local_definition())
            out.write(f"PyObject *py_{argument.name:s} = NULL;\n")

        values_dict = {"name": self.name}

        out.write(self._DEFINITION_GIL_ENSURE_TEMPLATE.format(**values_dict))

        for argument in self.args:
            python_object_string = argument.to_python_object(
                BORROWED=True,
                result=f"py_{argument.name:s}",
                sense="proxied",
            )
            out.write(python_object_string)

        values_dict = {"class_name": self.myclass.class_name}

        out.write(self._DEFINITION_METHODS_TEMPLATE.format(**values_dict))

        out.write(
            "    Py_result = PyObject_CallMethodObjArgs((PyObject *) "
            "((Object) self)->extension, method_name, "
        )
        for argument in self.args:
            out.write(f"py_{argument.name:s},")

        # Sentinal
        out.write("NULL);\n\n")

        self.error_set = True
        out.write(
            "    /* Check for Python errors */\n"
            "    if(PyErr_Occurred()) {\n"
            "        pytsk_fetch_error();\n"
            "\n"
            "        goto on_error;\n"
            "    }\n"
            "\n"
        )
        for argument in self.args:
            out.write(argument.python_proxy_post_call())

        # Now convert the Python value back to a value
        return_type = self.return_type.from_python_object(
            "Py_result", self.return_type.name, self, context="self"
        )
        out.write(f"    {return_type:s}")

        # python_object2 keeps the returned Wrapper's C pointer alive
        # after this callback returns to libtsk. Under free-threading,
        # concurrent proxied callbacks would race the read-decref-write
        # triple (double-decref of the old value, leak of the new).
        # Py_BEGIN_CRITICAL_SECTION (3.13+) serializes the swap; under
        # the GIL on older versions the original serialization still holds.
        if isinstance(self.return_type, Wrapper) and not isinstance(
            self.return_type, (StructWrapper, PointerStructWrapper)
        ):
            out.write(self._DEFINITION_CRITICAL_SECTION_TEMPLATE)
        else:
            out.write(
                "    if(Py_result != NULL) {\n"
                "        Py_DecRef(Py_result);\n"
                "    }\n"
                "    Py_DecRef(method_name);\n"
                "\n"
            )

        # Decref all our Python objects:
        for argument in self.args:
            out.write(
                f"    if(py_{argument.name:s} != NULL) {{\n"
                f"        Py_DecRef(py_{argument.name:s});\n"
                f"    }}\n"
            )

        return_type = self.return_type.return_value("func_return")
        out.write(
            f"    PyGILState_Release(gil_state);\n" f"\n" f"    {return_type:s}\n"
        )
        if self.error_set:
            out.write(
                "\n"
                "on_error:\n"
                "    if(Py_result != NULL) {\n"
                "        Py_DecRef(Py_result);\n"
                "    }\n"
                "    Py_DecRef(method_name);\n"
                "\n"
            )
            # Decref all our Python objects:
            for argument in self.args:
                out.write(
                    f"    if(py_{argument.name:s} != NULL) {{\n"
                    f"        Py_DecRef(py_{argument.name:s});\n"
                    f"    }}\n"
                )

            error_condition = self.error_condition()
            out.write(
                f"    PyGILState_Release(gil_state);\n"
                f"\n"
                f"    {error_condition:s}\n"
            )

        out.write("}\n\n")

    def error_condition(self):
        """Generates code to handle the C/C++ type in an error conditition."""
        values_dict = {"result": "func_return"}
        return self.return_type.error_value.format(**values_dict)

    def get_name(self):
        """Retrieves the name."""
        return f"Proxied{self.myclass.class_name:s}_{self.name:s}"

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        self._prototype(out)
        out.write(";\n")

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        name = self.get_name()
        if name in self.myclass.module.function_definitions:
            return

        self.myclass.module.function_definitions.add(name)

        self._prototype(out)
        self._write_definition(out)


class StructConstructor(ConstructorMethod):
    """Contructor method for a struct wrapper code generator."""

    _DEFINITION_TEMPLATE = """\
static int py{class_name:s}_init(py{class_name:s} *self, PyObject *args, PyObject *kwds) {{
    // Base is borrowed from another object.
    self->base = NULL;
    if(!PyObject_GC_IsTracked((PyObject *) self)) {{
        PyObject_GC_Track((PyObject *) self);
    }}
    return 0;
}}

"""

    _DESTRUCTOR_TEMPLATE = """\
static void {class_name:s}_dealloc(py{class_name:s} *self) {{
    struct _typeobject *ob_type = NULL;

    if(self != NULL) {{
        PyObject_GC_UnTrack((PyObject *) self);
        if(self->base != NULL) {{
            self->base = NULL;
        }}
        /* Drop the parent keepalive (python_object1/2 wired
         * by the C->Py struct getter that yielded this borrow).
         */
        if(self->python_object2 != NULL) {{
            Py_DecRef(self->python_object2);
            self->python_object2 = NULL;
        }}
        if(self->python_object1 != NULL) {{
            Py_DecRef(self->python_object1);
            self->python_object1 = NULL;
        }}
        ob_type = Py_TYPE(self);
        if(ob_type != NULL && ob_type->tp_free != NULL) {{
            ob_type->tp_free((PyObject*) self);
        }}
    }}
}}

"""

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        return Method.prototype(self, out)

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        values_dict = {"class_name": self.class_name}

        out.write(self._DEFINITION_TEMPLATE.format(**values_dict))

    def write_destructor(self, out):
        """Generates code of a destructor of the C/C++ type.

        We do not deallocate memory from structs. This is a real problem since struct
        memory is usually allocated in some proprietary way and we cant just call free
        on it when done.
        """
        values_dict = {"class_name": self.class_name}

        out.write(self._DESTRUCTOR_TEMPLATE.format(**values_dict))


class EmptyConstructor(ConstructorMethod):
    """Empty contructor method code generator."""

    _DEFINITION_TEMPLATE = """\
static int py{class_name:s}_init(py{class_name:s} *self, PyObject *args, PyObject *kwds) {{
    if(!PyObject_GC_IsTracked((PyObject *) self)) {{
        PyObject_GC_Track((PyObject *) self);
    }}
    return 0;
}}

"""

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        return Method.prototype(self, out)

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        values_dict = {"class_name": self.class_name}
        out.write(self._DEFINITION_TEMPLATE.format(**values_dict))


class ClassGenerator(BaseCodeGenerator):
    """Class code generator."""

    _NUMERIC_PROTOCOL_TEMPLATE = """\
static PyNumberMethods {class:s}_as_number = {{
    (binaryfunc)    0,             /* nb_add */
    (binaryfunc)    0,             /* nb_subtract */
    (binaryfunc)    0,             /* nb_multiply */
    (binaryfunc)    0,             /* nb_remainder */
    (binaryfunc)    0,             /* nb_divmod */
    (ternaryfunc)   0,             /* nb_power */
    (unaryfunc)     0,             /* nb_negative */
    (unaryfunc)     0,             /* nb_positive */
    (unaryfunc)     0,             /* nb_absolute */
    (inquiry)       {nonzero:s},   /* nb_bool */
    (unaryfunc)     0,             /* nb_invert */
    (binaryfunc)    0,             /* nb_lshift */
    (binaryfunc)    0,             /* nb_rshift */
    (binaryfunc)    0,             /* nb_and */
    (binaryfunc)    0,             /* nb_xor */
    (binaryfunc)    0,             /* nb_or */
    (unaryfunc)     {int:s},       /* nb_int */
    (void *)        NULL,          /* nb_reserved */
    (unaryfunc)     0,             /* nb_float */

    (binaryfunc)    0,             /* nb_inplace_add */
    (binaryfunc)    0,             /* nb_inplace_subtract */
    (binaryfunc)    0,             /* nb_inplace_multiply */
    (binaryfunc)    0,             /* nb_inplace_remainder */
    (ternaryfunc)   0,             /* nb_inplace_power */
    (binaryfunc)    0,             /* nb_inplace_lshift */
    (binaryfunc)    0,             /* nb_inplace_rshift */
    (binaryfunc)    0,             /* nb_inplace_and */
    (binaryfunc)    0,             /* nb_inplace_xor */
    (binaryfunc)    0,             /* nb_inplace_or */

    (binaryfunc)    0,             /* nb_floor_divide */
    (binaryfunc)    0,             /* nb_true_divide */
    (binaryfunc)    0,             /* nb_inplace_floor_divide */
    (binaryfunc)    0,             /* nb_inplace_true_divide */

    (unaryfunc)     0,             /* nb_index */
}};

"""

    _PY_TUPLE_OBJECT_TEMPLATE = """\
static PyTypeObject {class:s}_Type = {{
    PyVarObject_HEAD_INIT(NULL, 0)
    /* tp_name */
    "{module:s}.{class:s}",
    /* tp_basicsize */
    sizeof(py{class:s}),
    /* tp_itemsize */
    0,
    /* tp_dealloc */
    (destructor) {class:s}_dealloc,
    /* tp_print */
    0,
    /* tp_getattr */
    0,
    /* tp_setattr */
    0,
    /* tp_compare */
    0,
    /* tp_repr */
    0,
    /* tp_as_number */
    {numeric_protocol:s},
    /* tp_as_sequence */
    0,
    /* tp_as_mapping */
    0,
    /* tp_hash */
    0,
    /* tp_call */
    0,
    /* tp_str */
    (reprfunc) {tp_str!s},
    /* tp_getattro */
    (getattrofunc) {getattr_func!s},
    /* tp_setattro */
    0,
    /* tp_as_buffer */
    0,
    /* tp_flags */
    {tp_flags:s},
    /* tp_doc */
    "{docstring:s}",
    /* tp_traverse */
    {tp_traverse!s},
    /* tp_clear */
    {tp_clear!s},
    /* tp_richcompare */
    {tp_eq!s},
    /* tp_weaklistoffset */
    0,
    /* tp_iter */
    (getiterfunc) {iterator!s},
    /* tp_iternext */
    (iternextfunc) {iternext!s},
    /* tp_methods */
    {class:s}_methods,
    /* tp_members */
    0,
    /* tp_getset */
    {class:s}_get_set_definitions,
    /* tp_base */
    0,
    /* tp_dict */
    0,
    /* tp_descr_get */
    0,
    /* tp_descr_set */
    0,
    /* tp_dictoffset */
    0,
    /* tp_init */
    (initproc) py{class:s}_init,
    /* tp_alloc */
    0,
    /* tp_new */
    0,
}};

"""

    _STRUCT_TEMPLATE = """
typedef struct {{
    PyObject_HEAD
    {class_name:s} base;
    int base_is_python_object;
    int base_is_internal;
    PyObject *python_object1;
    PyObject *python_object2;
    int object_is_proxied;

    void (*initialise)(Gen_wrapper self, void *item);
}} py{class_name:s};
"""

    docstring = ""

    def __init__(self, class_name, base_class_name, module):
        """Initializes the code generator."""
        super().__init__()
        self.active = True
        self.attributes = GetattrMethod(class_name, base_class_name, self)
        self.base_class_name = base_class_name
        self.class_name = class_name
        self.constructor = EmptyConstructor(
            class_name, base_class_name, "Con", [], "", myclass=self
        )
        self.iterator = None
        self.methods = []
        self.modifier = set()
        self.module = module

    def _get_methods_string(self):
        string_parts = []
        for method in self.methods:
            method_string = method.get_string()
            string_parts.append(f"        {method_string:s}\n")

        return "".join(string_parts)

    def add_attribute(self, attr_name, attr_type, modifier, *args, **kwargs):
        """Add an attribute and register it with the type dispatcher."""
        try:
            if not self.module.classes[attr_type].is_active():
                return
        except KeyError:
            pass

        try:
            # All attribute references are always borrowed - that
            # means we dont want to free them after accessing them
            type_class = TypeDispatcher.dispatch(
                attr_name, f"BORROWED {attr_type:s}", *args, **kwargs
            )
        except KeyError:
            # TODO: fix that self.class_name is None.
            self.log(
                f"Unknown attribute type {attr_type:s} for {self.class_name!s}."
                f"{attr_name:s}"
            )
            return

        type_class.attributes.add(modifier)
        self.attributes.add_attribute(type_class)

    def add_constructor(self, method_name, args, return_type, docstring):
        """Add a constructor method."""
        if method_name.startswith("Con"):
            self.constructor = ConstructorMethod(
                self.class_name,
                self.base_class_name,
                method_name,
                args,
                return_type,
                myclass=self,
            )
            self.constructor.docstring = docstring

    def clone(self, new_class_name):
        """Clone the code generator."""
        result = ClassGenerator(new_class_name, self.class_name, self.module)
        result.constructor = self.constructor.clone(new_class_name)
        result.methods = [method.clone(new_class_name) for method in self.methods]
        result.attributes = self.attributes.clone(new_class_name)

        return result

    def code(self, out):
        """Generates code."""
        if not self.constructor:
            raise RuntimeError(f"No constructor found for class {self.class_name:s}")

        self.constructor.write_destructor(out)
        self.constructor.write_definition(out)
        if self.attributes:
            self.attributes.write_definition(out)

        for method in self.methods:
            method.write_definition(out)

            if hasattr(method, "proxied"):
                method.proxied.write_definition(out)

    def get_string(self):
        """Retrieves a string representation."""
        constructor = self.constructor.get_string()
        attributes = self.attributes.get_string()
        methods = self._get_methods_string()

        result = (
            f"#{self.docstring:s}\n"
            f"Class {self.class_name:s}({self.base_class_name:s}):\n"
            f"    Constructor:{constructor:s}\n"
            f"    Attributes:\n"
            f"{attributes:s}\n"
            f"    Methods:\n"
            f"{methods:s}"
        )
        return result

    def initialize(self):
        """Generates initializiation code of the C/C++ type."""
        # Release fetch_add publishes the entry: an acquire-load reader that sees the
        # bumped count is guaranteed to see the writes above.
        result = (
            f"{{\n"
            f"    int idx = TOTAL_CCLASSES.load(std::memory_order_relaxed);\n"
            f"    python_wrappers[idx].class_ref = (Object)&__{self.class_name:s};\n"
            f"    python_wrappers[idx].python_type = &{self.class_name:s}_Type;\n"
        )
        func_name = f"py{self.class_name:s}_initialize_proxies"

        if func_name in self.module.function_definitions:
            result += (
                f"    python_wrappers[idx].initialize_proxies = (void (*)"
                f"(Gen_wrapper, void *)) &{func_name:s};\n"
            )

        result += (
            "    (void) TOTAL_CCLASSES.fetch_add(1, std::memory_order_release);\n" "}\n"
        )
        return result

    def is_active(self):
        """Returns true if this class is active and should be generated"""
        if self.class_name in self.module.active_structs:
            return True

        if (
            not self.active
            or self.modifier
            and ("PRIVATE" in self.modifier or "ABSTRACT" in self.modifier)
        ):
            self.log(f"{self.class_name:s} is not active {self.modifier!s}")
            return False

        return True

    def numeric_protocol(self, out):
        """Generates code."""
        args = {"class": self.class_name}

        for data_type, func in [
            ("nonzero", self.numeric_protocol_nonzero),
            ("int", self.numeric_protocol_int),
        ]:
            definition = func()
            if definition:
                out.write(definition)
                args[data_type] = f"{self.class_name:s}_{data_type:s}"
            else:
                args[data_type] = "0"

        out.write(self._NUMERIC_PROTOCOL_TEMPLATE.format(**args))

        return f"&{self.class_name:s}_as_number"

    def numeric_protocol_int(self):
        """Generates code."""

    def numeric_protocol_nonzero(self):
        """Generates code."""
        return (
            f"static int {self.class_name:s}_nonzero(py{self.class_name:s} *v) {{\n"
            f"    return v->base != 0;\n"
            f"}}\n"
        )

    def prepare(self):
        """Prepare code generation."""

    def prototypes(self, out):
        """Write prototype suitable for .h file"""
        out.write(f"/* static PyTypeObject {self.class_name:s}_Type; */\n")

        self.constructor.prototype(out)

        out.write(
            f"static void {self.class_name:s}_dealloc(py{self.class_name:s} *self);\n"
        )
        if self.attributes:
            self.attributes.prototype(out)
        for method in self.methods:
            method.prototype(out)

            # Each method, except for close, needs a proxy method that
            # is called when the object is sub typed.
            if method.name == "close":
                continue

            method.proxied = ProxiedMethod(method, method.myclass)
            method.proxied.prototype(out)

    def PyGetSetDef(self, out):
        """Generates code of PyGetSetDef for the C/C++ type."""
        out.write(
            f"static PyGetSetDef {self.class_name:s}_get_set_definitions[] = {{\n"
        )
        if self.attributes:
            self.attributes.PyGetSetDef(out)

        out.write("""\
    {NULL, NULL, NULL, NULL, NULL}  /* Sentinel */
};

""")

    def PyMethodDef(self, out):
        """Generates code of PyMethodDef for the C/C++ type."""
        out.write(f"static PyMethodDef {self.class_name:s}_methods[] = {{\n")

        for method in self.methods:
            method.PyMethodDef(out)

        out.write("""\
    {NULL, NULL, 0, NULL}  /* Sentinel */
};

""")

    def PyTypeObject(self, out):
        """Generates code of PyTypeObject for the C/C++ type."""
        docstring = self.format_as_docstring(self.docstring)
        args = {
            "class": self.class_name,
            "docstring": f"{self.class_name:s}: {docstring:s}",
            "getattr_func": 0,
            "iterator": 0,
            "iternext": 0,
            "module": self.module.name,
            "tp_clear": 0,
            "tp_eq": 0,
            "tp_flags": "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE",
            "tp_str": 0,
            "tp_traverse": 0,
        }
        # Enums use a different struct layout (PyObject_HEAD + value only)
        # and override their dealloc/init, so they don't need GC support.
        if getattr(self, "supports_gc", True):
            args["tp_flags"] += " | Py_TPFLAGS_HAVE_GC"
            args["tp_traverse"] = "(traverseproc) Gen_wrapper_traverse"
            args["tp_clear"] = "(inquiry) Gen_wrapper_clear"

        if self.attributes:
            args["getattr_func"] = self.attributes.name

        args["numeric_protocol"] = self.numeric_protocol(out)
        if "ITERATOR" in self.modifier:
            args["iterator"] = "PyObject_SelfIter"
            args["iternext"] = f"py{self.class_name:s}_iternext"

        if "SELF_ITER" in self.modifier:
            args["iterator"] = f"py{self.class_name:s}___iter__"

        if "TP_STR" in self.modifier:
            args["tp_str"] = f"py{self.class_name:s}___str__"

        if "TP_EQUAL" in self.modifier:
            args["tp_eq"] = f"{self.class_name:s}_eq"

        out.write(self._PY_TUPLE_OBJECT_TEMPLATE.format(**args))

    def struct(self, out):
        """Generates code."""
        values_dict = {"class_name": self.class_name}

        out.write(self._STRUCT_TEMPLATE.format(**values_dict))


class StructGenerator(ClassGenerator):
    """Struct code generator."""

    _STRUCT_TEMPLATE = """
typedef struct {{
    PyObject_HEAD
    {class_name:s} *base;
    int base_is_python_object;
    int base_is_internal;
    PyObject *python_object1;
    PyObject *python_object2;
    int object_is_proxied;
    {class_name:s} *cbase;
}} py{class_name:s};
"""

    def __init__(self, class_name, module):
        """Initializes the code generator."""
        super().__init__(class_name, None, module)
        self.active = False
        self.constructor = None

    def get_string(self):
        """Retrieves a string representation."""
        attributes = self.attributes.get_string()

        return (
            f"# {self.docstring:s}\n"
            f"Struct {self.class_name:s}:\n"
            f"{attributes:s}\n"
        )

    def initialize(self):
        """Generates initializiation code of the C/C++ type."""
        return ""

    def prepare(self):
        """Prepare code generation."""
        # This is needed for late stage initialization - sometimes our class_name is
        # not know until now.
        if not self.constructor:
            self.constructor = StructConstructor(
                self.class_name, self.base_class_name, "Con", [], "void", myclass=self
            )
            self.attributes.rename_class_name(self.class_name)

            # pylint: disable=protected-access
            for x in self.attributes._attributes:
                x[1].attributes.add("FOREIGN")

    def struct(self, out):
        """Generates code."""
        values_dict = {"class_name": self.class_name}

        out.write(self._STRUCT_TEMPLATE.format(**values_dict))


class EnumConstructor(ConstructorMethod):
    """Contructor method for an enum code generator."""

    _DEFINITION_TEMPLATE = """\
{{
    const char *kwlist[] = {{"value", NULL}};

    if(!PyArg_ParseTupleAndKeywords(args, kwds, "O", (char **) kwlist, &self->value)) {{
        goto on_error;
    }}

    Py_IncRef(self->value);

    return 0;

on_error:
    return -1;
}}

"""

    _DESTRUCTOR_TEMPLATE = """\
static void {class_name:s}_dealloc(py{class_name:s} *self) {{
    struct _typeobject *ob_type = NULL;

    if(self != NULL) {{
        Py_DecRef(self->value);
        ob_type = Py_TYPE(self);
        if(ob_type != NULL && ob_type->tp_free != NULL) {{
            ob_type->tp_free((PyObject*) self);
        }}
    }}
}}
"""

    def prototype(self, out):
        """Generates code with a prototype of the C/C++ type."""
        return Method.prototype(self, out)

    def write_definition(self, out):
        """Generates code to define the C/C++ type."""
        self.myclass.modifier.add("TP_STR")
        self.myclass.modifier.add("TP_EQUAL")
        self._prototype(out)

        values_dict = {"class_name": self.class_name}

        out.write(self._DEFINITION_TEMPLATE.format(**values_dict))

    def write_destructor(self, out):
        """Generates code of a destructor of the C/C++ type."""
        values_dict = {"class_name": self.class_name}

        out.write(self._DESTRUCTOR_TEMPLATE.format(**values_dict))


class Enum(StructGenerator):
    """Enum code generator."""

    _STRUCT_ATTRIBUTE_TEMPLATE = """\
    integer_object = PyLong_FromLong({value:s});
    if(integer_object == NULL) {{
        Py_DecRef(type_object->tp_dict);
        type_object->tp_dict = NULL;
        return 0;
    }}
    if(PyDict_SetItemString(type_object->tp_dict, "{value:s}", integer_object) < 0) {{
        Py_DecRef(integer_object);
        Py_DecRef(type_object->tp_dict);
        type_object->tp_dict = NULL;
        return 0;
    }}
    Py_DecRef(integer_object);

"""

    _STRUCT_START_TEMPLATE = """
typedef struct {{
    PyObject_HEAD
    PyObject *value;
}} py{class_name:s};

int {class_name:s}_init_type(
    PyTypeObject *type_object )
{{
    type_object->tp_dict = PyDict_New();
    if(type_object->tp_dict == NULL) {{
        return 0;
    }}
"""

    # Enum types use a different struct layout (PyObject_HEAD + PyObject*
    # value) and cannot form Gen_wrapper-style cycles, so skip GC support.
    supports_gc = False

    def __init__(self, name, module):
        """Initializes the code generator."""
        super().__init__(name, module)
        self.active = True
        self.attributes = None
        self.name = name
        self.values = []

    def get_string(self):
        """Retrieves a string representation."""
        result = f"Enum {self.name:s}:\n"
        for attr in self.values:
            result += f"    {attr:s}\n"

        return result

    def initialize(self):
        """Generates initializiation code of the C/C++ type."""
        return "\n"

    def numeric_protocol_int(self):
        """Generates code."""
        method_name = f"{self.class_name:s}_int"
        type_name = f"py{self.class_name:s}"

        return (
            f"static PyObject *{method_name:s}({type_name:s} *self) {{\n"
            f"    Py_IncRef(self->value);\n"
            f"    return self->value;\n"
            f"}}\n"
        )

    def numeric_protocol_nonzero(self):
        """Generates code."""

    def prepare(self):
        """Prepare code generation."""
        self.constructor = EnumConstructor(
            self.class_name, self.base_class_name, "Con", [], "void", myclass=self
        )
        StructGenerator.prepare(self)

    def PyGetSetDef(self, out):
        """Generates code of PyGetSetDef for the C/C++ type."""
        out.write(
            f"static PyGetSetDef {self.class_name:s}_get_set_definitions[] = {{\n"
            f"    {{NULL, NULL, NULL, NULL, NULL}}  /* Sentinel */\n"
            f"}};\n"
            f"\n"
        )

    def PyMethodDef(self, out):
        """Generates code of PyMethodDef for the C/C++ type."""
        out.write(
            f"static PyMethodDef {self.class_name:s}_methods[] = {{\n"
            f"    {{NULL, NULL, 0, NULL}}  /* Sentinel */\n"
            f"}};\n"
            f"\n"
        )

    def struct(self, out):
        """Generates code."""
        values_dict = {"class_name": self.class_name}

        out.write(self._STRUCT_START_TEMPLATE.format(**values_dict))

        if self.values:
            out.write("    PyObject *integer_object = NULL;\n")

            for attr in self.values:
                values_dict = {"class_name": self.class_name, "value": attr}

                # Each enum value must succeed; otherwise the type's tp_dict is
                # partially populated and the module loads with broken constants. Bail
                # out cleanly so PyType_Ready never sees a half-initialized enum.
                out.write(self._STRUCT_ATTRIBUTE_TEMPLATE.format(**values_dict))

        out.write("""\
    return( 1 );
}

""")


class EnumType(Integer):
    """Enum type code generator."""

    BUILDSTR = "i"

    def __init__(self, name, data_type, *args, **kwargs):
        """Initializes the code generator."""
        super().__init__(name, data_type, *args, **kwargs)
        self.type = data_type

    def definition(self, default=None, **unused_kwargs):
        """Generates code to define the C/C++ type."""
        # Force the enum to be an int just in case the compiler chooses a random size.
        if default:
            return f"    int {self.name:s} = {default:s};\n"

        return f"    int UNUSED {self.name:s} = 0;\n"

    # pylint: disable=arguments-differ
    def to_python_object(self, name=None, result="Py_result", **unused_kwargs):
        """Generates code to a Python object into a C/C++ type."""
        name = name or self.name

        return f"    PyErr_Clear();\n" f"    {result:s} = PyLong_FromLong({name:s});\n"

    def pre_call(self, method, **unused_kwargs):
        """Generates code needed before a function call for the C/C++ type."""
        method.error_set = True

        return ""


class TypeDispatcher:
    """Type dispatcher."""

    _METHOD_ATTRIBUTES = ["BORROWED", "DESTRUCTOR", "IGNORE"]

    _TYPES = {}

    @classmethod
    def is_active(cls, data_type):
        """Detemines if a specific type is active."""
        type_class = cls._TYPES.get(data_type)
        return type_class and type_class.active

    @classmethod
    def dispatch(cls, name, data_type, *args, **kwargs):
        """Retrieves a specific code generator."""
        if not data_type:
            return PVoid(name, "void *")

        match = re.match("struct ([a-zA-Z0-9]+)_t *", data_type)
        if match:
            data_type = match.group(1)

        type_components = data_type.split()
        attributes = set()

        if type_components[0] in cls._METHOD_ATTRIBUTES:
            attributes.add(type_components.pop(0))

        data_type = " ".join(type_components)
        type_class = cls._TYPES[data_type]

        code_generator = type_class(name, data_type, *args, **kwargs)
        code_generator.attributes = attributes
        return code_generator

    @classmethod
    def get_code_generator(cls, name, data_type):
        """Retrieves a specific code generator.

        Args:
            name (str): name.
            data_type (str): data type.

        Raises:
          KeyError: if the type does not exist.
        """
        type_class = cls._TYPES[data_type]
        return type_class(name, data_type)

    @classmethod
    def register(cls, data_type, type_class):
        """Registers a code generator type."""
        cls._TYPES[data_type] = type_class

    @classmethod
    def register_alias(cls, data_type, alias):
        """Registers an alias (typedef) if the type exists."""
        if data_type in cls._TYPES:
            cls._TYPES[alias] = cls._TYPES[data_type]

    @classmethod
    def register_types(cls, types):
        """Registers code generator types."""
        for data_type, type_class in types.items():
            cls.register(data_type, type_class)


TypeDispatcher.register_types(
    {
        "char": Char,
        "char *": String,
        "char **": StringArray,
        "IN char *": String,
        "int16_t": Integer16,
        "int32_t": Integer32,
        "int64_t": Integer64,
        "int8_t": Integer8,
        "int": Integer,
        "IN unsigned char *": String,
        "long int": Integer,
        "long": Long,
        "off_t": Integer64,
        "OUT char *": StringOut,
        "OUT uint32_t *": PInteger32UnsignedOut,
        "OUT uint64_t *": PInteger64UnsignedOut,
        "OUT unsigned char *": StringOut,
        "PyObject *": PyObject,
        "size_t": Integer64Unsigned,
        "ssize_t": Integer64,
        "struct timeval": Timeval,
        "TDB_DATA": TDB_DATA,
        "TDB_DATA *": TDB_DATA_P,
        "time_t": Integer64,
        "TSK_INUM_T": Integer,
        "uint16_t": Integer16Unsigned,
        "uint32_t": Integer32Unsigned,
        "uint64_t": Integer64Unsigned,
        "uint8_t": Integer8Unsigned,
        "unsigned char *": String,
        "unsigned int": Integer,
        "unsigned long int": LongUnsigned,
        "unsigned long": LongUnsigned,
        "void *": PVoid,
        "void": Void,
        "ZString": ZString,
    }
)


class HeaderParser(lexer.SelfFeederMixIn):
    """SleuthKit C/C++ header file parser (lexer)."""

    _TOKENS = [
        ["INITIAL", r"#define\s+", "PUSH_STATE", "DEFINE"],
        ["DEFINE", r"([A-Za-z_0-9]+)\s+[^\n]+", "DEFINE,POP_STATE", None],
        ["DEFINE", r"\n", "POP_STATE", None],
        # Ignore macros with args
        ["DEFINE", r"\([^\n]+", "POP_STATE", None],
        # Recognize ansi C comments
        [".", r"/\*(.)", "PUSH_STATE", "COMMENT"],
        ["COMMENT", r"(.+?)\*/\s+", "COMMENT_END,POP_STATE", None],
        ["COMMENT", r"(.+)", "COMMENT", None],
        # And C++ comments
        [".", r"//([^\n]+)", "COMMENT", None],
        # An empty line clears the current comment
        [".", r"\r?\n\r?\n", "CLEAR_COMMENT", None],
        # Ignore whitespace
        [".", r"\s+", "SPACE", None],
        [".", r"\\\n", "SPACE", None],
        # Recognize CCLASS() definitions
        [
            "INITIAL",
            r"^([A-Z]+)?\s*CCLASS\(([A-Z_a-z0-9]+)\s*,\s*([A-Z_a-z0-9]+)\)",
            "PUSH_STATE,CCLASS_START",
            "CCLASS",
        ],
        [
            "CCLASS",
            (
                r"^\s*(FOREIGN|ABSTRACT|PRIVATE)?([0-9A-Z_a-z ]+( |\*))"
                r"METHOD\(([A-Z_a-z0-9]+),\s*([A-Z_a-z0-9]+),?"
            ),
            "PUSH_STATE,METHOD_START",
            "METHOD",
        ],
        [
            "METHOD",
            r"\s*([0-9A-Z a-z_]+\s+\*?\*?)([0-9A-Za-z_]+),?",
            "METHOD_ARG",
            None,
        ],
        ["METHOD", r"\);", "POP_STATE,METHOD_END", None],
        [
            "CCLASS",
            r"^\s*(FOREIGN|ABSTRACT)?([0-9A-Z_a-z ]+\s+\*?)\s*([A-Z_a-z0-9]+)\s*;",
            "CCLASS_ATTRIBUTE",
            None,
        ],
        ["CCLASS", "END_CCLASS", "END_CCLASS,POP_STATE", None],
        # Recognize struct definitions (With name)
        [
            "INITIAL",
            r"([A-Z_a-z0-9 ]+)?struct\s+([A-Z_a-z0-9]+)\s+{",
            "PUSH_STATE,STRUCT_START",
            "STRUCT",
        ],
        # Without name (using typedef)
        [
            "INITIAL",
            r"typedef\s+struct\s+{",
            "PUSH_STATE,TYPEDEF_STRUCT_START",
            "STRUCT",
        ],
        [
            "STRUCT",
            r"^\s*([0-9A-Z_a-z ]+\s+\*?)\s*([A-Z_a-z0-9]+)(?:\[([A-Z_a-z0-9]+)\])?\s*;",
            "STRUCT_ATTRIBUTE",
            None,
        ],
        [
            "STRUCT",
            r"^\s*([0-9A-Z_a-z ]+)\*\s+([A-Z_a-z0-9]+)\s*;",
            "STRUCT_ATTRIBUTE_PTR",
            None,
        ],
        # Struct ended with typedef
        ["STRUCT", r"}\s+([0-9A-Za-z_]+);", "POP_STATE,TYPEDEF_STRUCT_END", None],
        ["STRUCT", "}", "POP_STATE,STRUCT_END", None],
        # Handle recursive struct or union definition. At the moment we cannot handle
        # them at all.
        [
            "(RECURSIVE_)?STRUCT",
            r"(struct|union)\s+([_A-Za-z0-9]+)?\s*{",
            "PUSH_STATE",
            "RECURSIVE_STRUCT",
        ],
        ["RECURSIVE_STRUCT", r"}\s+[0-9A-Za-z]+", "POP_STATE", None],
        ["RECURSIVE_STRUCT", "};", "POP_STATE", None],
        # Process enums (2 forms - named and typedefed)
        ["INITIAL", r"enum\s+([0-9A-Za-z_]+)\s+{", "PUSH_STATE,ENUM_START", "ENUM"],
        # Unnamed
        ["INITIAL", r"typedef\s+enum\s+{", "PUSH_STATE,TYPEDEF_ENUM_START", "ENUM"],
        ["ENUM", r"([0-9A-Za-z_]+)\s+=[^\n]+", "ENUM_VALUE", None],
        # Typedefed ending
        ["ENUM", r"}\s+([0-9A-Za-z_]+);", "POP_STATE,TYPEDEFED_ENUM_END", None],
        ["ENUM", r"}", "POP_STATE,ENUM_END", None],
        ["INITIAL", r"BIND_STRUCT\(([0-9A-Za-z_ \*]+)\)", "BIND_STRUCT", None],
        # A simple typedef of one type for another type:
        ["INITIAL", r"typedef ([A-Za-z_0-9]+) +([^;]+);", "SIMPLE_TYPEDEF", None],
    ]

    def __init__(self, name, verbose=0, base=""):
        """Initializes the lexer."""
        super().__init__(verbose=verbose)
        self.base = base
        self.current_class = None
        self.current_comment = ""
        self.current_enum = None
        self.current_method = None
        self.current_struct = None
        self.module = Module(name)

        file_object = io.BytesIO(
            b"// Base object\n" b"CCLASS(Object, Obj)\n" b"END_CCLASS\n"
        )
        self.parse_fd(file_object)

    def _parse_header_file(self, filename):
        """Parse a header file."""
        with open(filename, "rb") as file_object:
            self.parse_fd(file_object)

        if filename not in self.module.files:
            if filename.startswith(self.base):
                filename = filename[len(self.base) :]

            self.module.headers += f'#include "{filename:s}"\n'
            self.module.files.append(filename)

    def generate_code(self, file_object):
        """Generates code."""
        self.module.write(file_object)

    def parse_filenames(self, filenames):
        """Parse header files."""
        for filename in filenames:
            self._parse_header_file(filename)

        # Second pass
        for filename in filenames:
            self._parse_header_file(filename)

    # The following methods are state handlers that have a calling convention.
    # pylint: disable=invalid-name

    def BIND_STRUCT(self, unused_token, match):
        """Handle a BIND_STRUCT state."""
        struct_name = match.group(1)
        self.module.active_structs.add(struct_name)
        self.module.active_structs.add(f"{struct_name:s} *")

    def CCLASS_ATTRIBUTE(self, unused_token, match):
        """Handle a CCLASS_ATTRIBUTE state."""
        attribute_modifier = match.group(1) or ""
        attribute_type = match.group(2).strip()
        attribute_name = match.group(3).strip()
        self.current_class.add_attribute(
            attribute_name, attribute_type, attribute_modifier
        )

    def CCLASS_START(self, unused_token, match):
        """Handle a CCLASS_START state."""
        class_name = match.group(2).strip()
        base_class_name = match.group(3).strip()

        try:
            self.current_class = self.module.classes[base_class_name].clone(class_name)
        except (KeyError, AttributeError):
            if self.verbose > 1:
                self.log(f"Base class {base_class_name:s} is not defined.")

            self.current_class = ClassGenerator(
                class_name, base_class_name, self.module
            )

        self.current_class.docstring = self.current_comment
        self.current_class.modifier.add(match.group(1))
        self.module.add_class(self.current_class, Wrapper)

        TypeDispatcher.register(f"{class_name:s} *", PointerWrapper)

    def CLEAR_COMMENT(self, unused_token, unused_match):
        """Handle a CLEAR_COMMENT state."""
        self.current_comment = ""

    def COMMENT(self, unused_token, match):
        """Handle a COMMENT state."""
        self.current_comment += match.group(1) + "\n"

    def COMMENT_END(self, unused_token, match):
        """Handle a COMMENT_END state."""
        self.current_comment += match.group(1)

    def DEFINE(self, unused_token, match):
        """Handle a DEFINE state."""
        line = match.group(0)
        line = line.split("/*")[0]
        if '"' in line:
            data_type = "string"
        else:
            data_type = "integer"

        name = match.group(1).strip()
        if (
            len(name) > 3
            and name[0] != "_"
            and name == name.upper()
            and name not in self.module.constants_denylist
        ):
            self.module.add_constant(name, data_type=data_type)

    def END_CCLASS(self, unused_token, unused_match):
        """Handle a END_CCLASS state."""
        self.current_class = None

    def ENUM_END(self, unused_token, unused_match):
        """Handle a ENUM_END state."""
        self.module.classes[self.current_enum.name] = self.current_enum

        # For now we just treat enums as an integer, and also add them to the constant
        # table. In future it would be nice to have them as a proper Python object so
        # we can override the "__unicode__", "__str__" and "__int__" methods.

        for attr in self.current_enum.values:
            self.module.add_constant(attr, data_type="integer")

        TypeDispatcher.register(self.current_enum.name, EnumType)

        self.current_enum = None

    def ENUM_START(self, unused_token, match):
        """Handle a ENUM_START state."""
        self.current_enum = Enum(match.group(1).strip(), self.module)

    def ENUM_VALUE(self, unused_token, match):
        """Handle a ENUM_VALUE state."""
        self.current_enum.values.append(match.group(1).strip())

    def METHOD_ARG(self, unused_token, match):
        """Handle a METHOD_ARG state."""
        arg_name = match.group(2).strip()
        arg_type = match.group(1).strip()
        if self.current_method:
            self.current_method.add_arg(arg_type, arg_name)

    def METHOD_END(self, unused_token, unused_match):
        """Handle a METHOD_END state."""
        if not self.current_method:
            return

        if isinstance(self.current_method, ConstructorMethod):
            self.current_class.constructor = self.current_method
        else:
            for index, method in enumerate(self.current_class.methods):
                # Try to replace existing methods with this new method.
                if method.name == self.current_method.name:
                    self.current_class.methods[index] = self.current_method
                    self.current_method = None
                    return

            # Method does not exist, just add to the end.
            self.current_class.methods.append(self.current_method)

        self.current_method = None

    def METHOD_START(self, unused_token, match):
        """Handle a METHOD_START state."""
        return_type = match.group(2).strip()
        method_name = match.group(5).strip()
        modifier = match.group(1) or ""

        if "PRIVATE" in modifier:
            return

        # Is it a regular method or a constructor?
        self.current_method = Method
        if return_type == self.current_class.class_name and method_name.startswith(
            "Con"
        ):
            self.current_method = ConstructorMethod
        elif method_name == "iternext":
            self.current_method = IteratorMethod
            self.current_class.modifier.add("ITERATOR")
        elif method_name == "__iter__":
            self.current_method = SelfIteratorMethod
            self.current_class.modifier.add("SELF_ITER")
        elif method_name == "__str__":
            self.current_class.modifier.add("TP_STR")

        self.current_method = self.current_method(
            self.current_class.class_name,
            self.current_class.base_class_name,
            method_name,
            [],
            return_type,
            myclass=self.current_class,
        )
        self.current_method.docstring = self.current_comment
        self.current_method.modifier = modifier

    def SIMPLE_TYPEDEF(self, unused_token, match):
        """Handle a SIMPLE_TYPEDEF state."""
        TypeDispatcher.register_alias(match.group(1).strip(), match.group(2).strip())

    def STRUCT_ATTRIBUTE(self, unused_token, match):
        """Handle a STRUCT_ATTRIBUTE state."""
        name = match.group(2).strip()
        data_type = match.group(1).strip()
        array_size = match.group(3)
        if array_size is not None:
            array_size = array_size.strip()
            self.current_struct.add_attribute(
                name, data_type, "", array_size=array_size
            )
        else:
            self.current_struct.add_attribute(name, data_type, "")

    def STRUCT_ATTRIBUTE_PTR(self, unused_token, match):
        """Handle a STRUCT_ATTRIBUTE_PTR state."""
        attribute_type = match.group(1).strip()
        attribute_name = match.group(2).strip()
        self.current_struct.add_attribute(attribute_name, f"{attribute_type:s} *", "")

    def STRUCT_END(self, unused_token, unused_match):
        """Handle a STRUCT_END state."""
        self.module.add_class(self.current_struct, StructWrapper)
        TypeDispatcher.register(
            f"{self.current_struct.class_name:s} *", PointerStructWrapper
        )
        self.current_struct = None

    def STRUCT_START(self, unused_token, match):
        """Handle a STRUCT_START state."""
        self.current_struct = StructGenerator(match.group(2).strip(), self.module)
        self.current_struct.docstring = self.current_comment
        self.current_struct.modifier.add(match.group(1))

    def TYPEDEFED_ENUM_END(self, token, match):
        """Handle a TYPEDEFED_ENUM_END state."""
        self.current_enum.name = self.current_enum.class_name = match.group(1)
        self.ENUM_END(token, match)

    def TYPEDEF_ENUM_START(self, unused_token, unused_match):
        """Handle a TYPEDEF_ENUM_START state."""
        self.current_enum = Enum(None, self.module)

    def TYPEDEF_STRUCT_END(self, token, match):
        """Handle a TYPEDEF_STRUCT_END state."""
        self.current_struct.class_name = match.group(1).strip()

        self.STRUCT_END(token, match)

    def TYPEDEF_STRUCT_START(self, unused_token, unused_match):
        """Handle a TYPEDEF_STRUCT_START state."""
        self.current_struct = StructGenerator(None, self.module)
        self.current_struct.docstring = self.current_comment


if __name__ == "__main__":
    verbose_level = 1 if DEBUG > 0 else 0

    parser = HeaderParser("pytsk3", verbose=verbose_level)

    for arg in sys.argv[1:]:
        with open(arg, "rb") as fd:
            parser.parse_fd(fd)

    if verbose_level > 0:
        parser.log("second parse")

    for arg in sys.argv[1:]:
        with open(arg, "rb") as fd:
            parser.parse_fd(fd)

    parser.generate_code(sys.stdout)

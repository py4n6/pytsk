#!/usr/bin/python
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

AFF4 uses a reference count system for memory management similar in
many ways to the native Python system. The basic idea is that memory
returned by the library always carries a new reference. When the
caller is done with the memory, they must call aff4_free() on the
memory, afterwhich the memory is considered invalid. The memory may
still not be freed at this point depending on its total reference
count.

New references may be taken to the same memory at any time using the
aff4_incref() function. This increases the reference count of the
object, and prevents it from being really freed until the correct
number of aff4_free() calls are made to it.

This idea is important for example in the following sequence:

FileLikeObject fd = resolver->create(resolver, "w");
RDFURN uri = fd->urn;

Now uri hold a reference to the urn attribute of fd, but that
attribute is actually owned by fd. If fd is freed in future, e.g. (the
close method actually frees the fd implicitely):

fd->close(fd);

Now the uri object is dangling. To prevent fd->urn from disappearing
when fd is freed, we need to take another reference to it:

FileLikeObject fd = resolver->create(resolver, "w");
RDFURN uri = fd->urn;
aff4_incref(uri);

fd->close(fd);

Now uri is valid (but fd is no longer valid). When we are finished
with uri we just call:

aff4_free(uri);


Python Integration
------------------

For every AFF4 object, we create a Python wrapper object of the
corresponding type. The wrapper object contains Python wrapper methods
to allow access to the AFF4 object methods, as well as getattr methods
for attributes. It is very important to allow Python to inherit from C
classes directly - this requires every internal C method call to be
diverted to the Python object.

The C object looks like this normally:

struct obj {
    __class__ pointer to static struct initialised with C method pointers

... Some private members
... Attributes;

/* Following are the methods */
    int (*method)(struct obj *self, ....);
};

I.e. when the method is called the struct.method member is
dereferenced to find the location of the function handling it, the
object is stuffed into the first arg, and the parameters are stuffed
into following args.

Directing Python calls
----------------------

The Python object which is created is a proxy for the c object. When
Python methods are called in the Python object, they need to be
directed into the C structure and a C call must be made, then the
return value must be reconverted into Python objects and returned into
Python. This occurs automatically by the wrapper:

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
    set up c declerations for all args - call .definition() on all the args and return type

    parse argument using PyArg_ParseTupleAndKeywords

    Precall preparations

    Make the C call

    Post call processing of the returned value (check for errors etc)

    Convert the return value to a Python object using:
    return_type.to_Python_object()

    return the Python object or raise an exception
};

So the aim of the wrapper function is to convert Python args to C
args, find the C method corresponding to the method name by
dereferencing the c object and then call it.


The problem now is what happens when a C method internally calls
another method. This is a problem because the C method has no idea its
running within Python and so will just call the regular C method that
was there already. This makes it impossible to subclass the class and
update the C method with a Python method. What we really want is when
a C method is called internally, we want to end up calling the Python
object instead to allow a purely Python implementation to override the
C method.

This happens by way of a ProxiedMethod - A proxied method is in a
sense the reverse of the wrapper method:

return_type ProxyCLASSNAME_method(CLASSNAME self, ....) {
   Take all C args and create Python objects from them

   Dereference the object extension ((Object) self)->extension to
   obtain the Python object which wraps this class.

   If an extension does not exist, just call the method as normal,
   otherwise make a Python call on the wrapper object.

   Convert the returned Python object to a C type and return it.
};

To make all this work we have the following structures:
struct PythonWrapper {
  PyObject_HEAD
  struct CLASSNAME *base

       - This is a copy of the item, with all function pointer
         pointing at proxy functions. We can always get the original C
         function pointers through base->__class__

       - We also set the base object extension to be the Python
         object: ((Object) base)->extension = PythonWrapper. This
         allows us to get back the Python object from base.
};


When a Python method is invoked, we use cbase to find the C method
pointer, but we pass to it base:

self->base->__class__->method(self->base, ....)

base is a proper C object which had its methods dynamically replaced
with proxies. Now if an internal C method is called, the method will
dereference base and retrieve the proxied method. Calling the
proxied method will retreive the original Python object from the
object extension and make a Python call.

In the case where a method is not overridden by Python, internal C
method calls will generate an unnecessary conversion from C to Python
and then back to C.

Memory management in Python extension
-------------------------------------

When calling a method which returns a new reference, we just store the
reference in the "base" member of the Python object. When Python
garbage collects our Python object, we call aff4_free() on it.

The getattr method creates a new Python wrapper object of the correct
type, and sets its base attribute to point at the target AFF4
object. We then aff4_incref() the target to ensure that it does not
get freed until we are finished with it.


   Python Object
  -----
 |  P1 |    C Object
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

   Figure 1: Python object 1 owns C1's memory (when P1 is GC'ed C1 is
             freed). A reference to a member of C1 is made via P1's
             getattr method. The getattr method creates P2 to provide
             access to C2 by setting base to C2's address. We need to
             guarantee however, that C2 will not be freed suddenly
             (e.g. if C1 is freed). We therefore increase C2's
             reference count using aff4_incref();
"""

import io
import os
import pdb
import re
import sys

import lexer

DEBUG = 0

# The pytsk3 version.
VERSION = "20190507"

# These functions are used to manage library memory.
FREE = "aff4_free"
INCREF = "aff4_incref"
CURRENT_ERROR_FUNCTION = "aff4_get_current_error"
CONSTANTS_BLACKLIST = ["TSK3_H_"]

# Some constants.
DOCSTRING_RE = re.compile("[ ]*\n[ \t]+[*][ ]?")


def dispatch(name, type, *args, **kwargs):
    if not type:
        return PVoid(name)

    m = re.match("struct ([a-zA-Z0-9]+)_t *", type)
    if m:
        type = m.group(1)

    type_components = type.split()
    attributes = set()

    if type_components[0] in method_attributes:
        attributes.add(type_components.pop(0))

    type = " ".join(type_components)
    result = type_dispatcher[type](name, type, *args, **kwargs)

    result.attributes = attributes

    return result


def log(msg):
    if DEBUG > 0:
        sys.stderr.write("{0:s}\n".format(msg))


def format_as_docstring(string):
    # Remove C/C++ comment code statements.
    string = DOCSTRING_RE.sub("\n", string)
    byte_string = string.encode("unicode-escape")
    # Escapes double quoted string. We need to run this after unicode-escape to
    # prevent this operation to escape the escape character (\). In Python 3
    # the replace method requires the arguments to be byte strings.
    byte_string = byte_string.replace(b"\"", b"\\\"")
    # Make sure to return the string a Unicode otherwise in Python 3 the string
    # is prefixed with b when written or printed.
    return byte_string.decode("utf-8")


class Module(object):
    public_api = None
    public_header = None

    def __init__(self, name):
        self.name = name
        self.constants = set()
        self.constants_blacklist = CONSTANTS_BLACKLIST
        self.classes = {}
        self.headers = "#include <Python.h>\n"
        self.files = []
        self.active_structs = set()
        self.function_definitions = set()

    init_string = ""

    def initialization(self):
        result = self.init_string + (
            "\n"
            "talloc_set_log_fn((void (*)(const char *)) printf);\n"
            "// DEBUG: talloc_enable_leak_report();\n"
            "// DEBUG: talloc_enable_leak_report_full();\n")

        for cls in self.classes.values():
            if cls.is_active():
                result += cls.initialise()

        return result

    def add_constant(self, constant, type="numeric"):
        """This will be called to add #define constant macros."""
        self.constants.add((constant, type))

    def add_class(self, cls, handler):
        self.classes[cls.class_name] = cls

        # Make a wrapper in the type dispatcher so we can handle
        # passing this class from/to Python
        type_dispatcher[cls.class_name] = handler

    def get_string(self):
        """Retrieves a string representation."""
        result = "Module {0:s}\n".format(self.name)
        classes_list = list(self.classes.values())
        classes_list.sort(key=lambda cls: cls.class_name)
        for cls in classes_list:
            if cls.is_active():
                result += "    {0:s}\n".format(cls.get_string())

        constants_list = list(self.constants)
        constants_list.sort()
        result += "Constants:\n"
        for name, _ in constants_list:
            result += " {0:s}\n".format(name)

        return result

    def private_functions(self):
        """Emits hard coded private functions for doing various things"""
        values_dict = {
            "classes_length": len(self.classes) + 1,
            "get_current_error": CURRENT_ERROR_FUNCTION}

        return """
/* The following is a static array mapping CLASS() pointers to their
 * Python wrappers. This is used to allow the correct wrapper to be
 * chosen depending on the object type found - regardless of the
 * prototype.
 *
 * This is basically a safer way for us to cast the correct Python type
 * depending on context rather than assuming a type based on the .h
 * definition. For example consider the function
 *
 * AFFObject Resolver.open(uri, mode)
 *
 * The .h file implies that an AFFObject object is returned, but this is
 * not true as most of the time an object of a derived class will be
 * returned. In C we cast the returned value to the correct type. In the
 * Python wrapper we just instantiate the correct Python object wrapper
 * at runtime depending on the actual returned type. We use this lookup
 * table to do so.
 */
static int TOTAL_CLASSES=0;

/* This is a global reference to this module so classes can call each
 * other.
 */
static PyObject *g_module = NULL;

#define CONSTRUCT_INITIALIZE(class, virt_class, constructor, object, ...) \\
    (class)(((virt_class) (&__ ## class))->constructor(object, ## __VA_ARGS__))

#undef BUFF_SIZE
#define BUFF_SIZE 10240

/* Python compatibility macros
 */
#if !defined( PyMODINIT_FUNC )
#if PY_MAJOR_VERSION >= 3
#define PyMODINIT_FUNC PyObject *
#else
#define PyMODINIT_FUNC void
#endif
#endif /* !defined( PyMODINIT_FUNC ) */

#if !defined( PyVarObject_HEAD_INIT )
#define PyVarObject_HEAD_INIT( type, size ) \\
    PyObject_HEAD_INIT( type ) \\
    size,

#endif /* !defined( PyVarObject_HEAD_INIT ) */

#if PY_MAJOR_VERSION >= 3
#define Py_TPFLAGS_HAVE_ITER		0
#endif

#if !defined( Py_TYPE )
#define Py_TYPE( object ) \\
    ( ( (PyObject *) object )->ob_type )

#endif /* !defined( Py_TYPE ) */

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

/* Create the relevant wrapper from the item based on the lookup table.
 */
Gen_wrapper new_class_wrapper(Object item, int item_is_python_object) {{
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
    for(cls = (Object) item->__class__; cls != cls->__super__; cls = cls->__super__) {{
        for(cls_index = 0; cls_index < TOTAL_CLASSES; cls_index++) {{
            python_wrapper = &(python_wrappers[cls_index]);

            if(python_wrapper->class_ref == cls) {{
                PyErr_Clear();

                result = (Gen_wrapper) _PyObject_New(python_wrapper->python_type);
                result->base = item;
                result->base_is_python_object = item_is_python_object;
                result->base_is_internal = 1;
                result->python_object1 = NULL;
                result->python_object2 = NULL;

                python_wrapper->initialize_proxies(result, (void *) item);

                return result;
            }}
        }}
    }}
    PyErr_Format(PyExc_RuntimeError, "Unable to find a wrapper for object %s", NAMEOF(item));

    return NULL;
}}

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
   int *error_type = (int *)aff4_get_current_error(&buffer);

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
static int check_method_override(PyObject *self, PyTypeObject *type, char *method) {{
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

#if PY_MAJOR_VERSION >= 3
    py_method = PyUnicode_FromString(method);
#else
    py_method = PyString_FromString(method);
#endif
    number_of_items = PySequence_Size(mro);

    for(item_index = 0; item_index < number_of_items; item_index++) {{
        item_object = PySequence_GetItem(mro, item_index);

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
        if(dict != NULL && PySequence_Contains(dict, py_method)) {{
            found = 1;
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

/* Fetches the Python error (exception)
 */
void pytsk_fetch_error(void) {{
    PyObject *exception_traceback = NULL;
    PyObject *exception_type = NULL;
    PyObject *exception_value = NULL;
    PyObject *string_object = NULL;
    char *str_c = NULL;
    char *error_str = NULL;
    int *error_type = (int *) {get_current_error:s}(&error_str);

#if PY_MAJOR_VERSION >= 3
    PyObject *utf8_string_object  = NULL;
#endif

    // Fetch the exception state and convert it to a string:
    PyErr_Fetch(&exception_type, &exception_value, &exception_traceback);

    string_object = PyObject_Repr(exception_value);

#if PY_MAJOR_VERSION >= 3
    utf8_string_object = PyUnicode_AsUTF8String(string_object);

    if(utf8_string_object != NULL) {{
        str_c = PyBytes_AsString(utf8_string_object);
    }}
#else
    str_c = PyString_AsString(string_object);
#endif

    if(str_c != NULL) {{
        strncpy(error_str, str_c, BUFF_SIZE-1);
        error_str[BUFF_SIZE - 1] = 0;
        *error_type = ERuntimeError;
    }}
    PyErr_Restore(exception_type, exception_value, exception_traceback);

#if PY_MAJOR_VERSION >= 3
    if( utf8_string_object != NULL ) {{
        Py_DecRef(utf8_string_object);
    }}
#endif
    Py_DecRef(string_object);

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
    }}
#if PY_MAJOR_VERSION < 3
    if(result == 0) {{
        PyErr_Clear();

        result = PyObject_IsInstance(integer_object, (PyObject *) &PyInt_Type);

        if(result == -1) {{
            pytsk_fetch_error();

            return (uint64_t) -1;

        }} else if(result != 0) {{
            PyErr_Clear();

#if defined( HAVE_LONG_LONG )
            long_value = PyInt_AsUnsignedLongLongMask(integer_object);
#else
            long_value = PyInt_AsUnsignedLongMask(integer_object);
#endif
        }}
    }}
#endif /* PY_MAJOR_VERSION < 3 */
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

""".format(**values_dict)

    def initialise_class(self, class_name, out, done=None):
        if done and class_name in done:
            return

        done.add(class_name)

        cls = self.classes[class_name]
        """Write out class initialisation code into the main init function."""
        if cls.is_active():
            base_class = self.classes.get(cls.base_class_name)

            if base_class and base_class.is_active():
                # We have a base class - ensure it gets written out
                # first:
                self.initialise_class(cls.base_class_name, out, done)

                # Now assign ourselves as derived from them
                out.write(
                    "    {0:s}_Type.tp_base = &{1:s}_Type;".format(
                        cls.class_name, cls.base_class_name))

            values_dict = {
                "name": cls.class_name}

            out.write((
                "    {name:s}_Type.tp_new = PyType_GenericNew;\n"
                "    if (PyType_Ready(&{name:s}_Type) < 0) {{\n"
                "        goto on_error;\n"
                "    }}\n"
                "    Py_IncRef((PyObject *)&{name:s}_Type);\n"
                "    PyModule_AddObject(module, \"{name:s}\", (PyObject *)&{name:s}_Type);\n").format(
                    **values_dict))

    def write(self, out):
        # Write the headers
        if self.public_api:
            self.public_api.write(
                "#ifdef BUILDING_DLL\n"
                "#include \"misc.h\"\n"
                "#else\n"
                "#include \"aff4_public.h\"\n"
                "#endif\n")

        # Prepare all classes
        for cls in self.classes.values():
            cls.prepare()

        out.write((
            "/*************************************************************\n"
            " * Autogenerated module {0:s}\n"
            " *\n"
            " * This module was autogenerated from the following files:\n").format(
                self.name))

        for filename in self.files:
            out.write(" * {0:s}\n".format(filename))

        out.write(
            " *\n"
            " * This module implements the following classes:\n")
        out.write(self.get_string())
        out.write(
            " ************************************************************/\n")
        out.write(self.headers)
        out.write(self.private_functions())

        for cls in self.classes.values():
            if cls.is_active():
                out.write(
                    "/******************** {0:s} ***********************/".format(
                        cls.class_name))
                cls.struct(out)
                cls.prototypes(out)

        out.write(
            "/*****************************************************\n"
            " *           Implementation\n"
            " ****************************************************/\n"
            "\n")

        for cls in self.classes.values():
            if cls.is_active():
                cls.PyMethodDef(out)
                cls.PyGetSetDef(out)
                cls.code(out)
                cls.PyTypeObject(out)

        # Write the module initializer
        values_dict = {
            "module": self.name,
            "version": VERSION,
            "version_length": len(VERSION)}

        out.write((
            "/* Retrieves the {module:s} version\n"
            " * Returns a Python object if successful or NULL on error\n"
            " */\n"
            "PyObject *{module:s}_get_version(PyObject *self, PyObject *arguments) {{\n"
            "    const char *errors = NULL;\n"
            "    return(PyUnicode_DecodeUTF8(\"{version:s}\", (Py_ssize_t) {version_length:d}, errors));\n"
            "}}\n"
            "\n"
            "static PyMethodDef {module:s}_module_methods[] = {{\n"
            "    {{ \"get_version\",\n"
            "        (PyCFunction) {module:s}_get_version,\n"
            "        METH_NOARGS,\n"
            "        \"get_version() -> String\\n\"\n"
            "        \"\\n\"\n"
            "        \"Retrieves the version.\" }},\n"
            "\n"
            "    {{NULL, NULL, 0, NULL}}  /* Sentinel */\n"
            "}};\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "\n"
            "/* The {module:s} module definition\n"
            " */\n"
            "PyModuleDef {module:s}_module_definition = {{\n"
            "	PyModuleDef_HEAD_INIT,\n"
            "\n"
            "	/* m_name */\n"
            "	\"{module:s}\",\n"
            "	/* m_doc */\n"
            "	\"Python {module:s} module.\",\n"
            "	/* m_size */\n"
            "	-1,\n"
            "	/* m_methods */\n"
            "	{module:s}_module_methods,\n"
            "	/* m_reload */\n"
            "	NULL,\n"
            "	/* m_traverse */\n"
            "	NULL,\n"
            "	/* m_clear */\n"
            "	NULL,\n"
            "	/* m_free */\n"
            "	NULL,\n"
            "}};\n"
            "\n"
            "#endif /* PY_MAJOR_VERSION >= 3 */\n"
            "\n"
            "/* Initializes the {module:s} module\n"
            " */\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "PyMODINIT_FUNC PyInit_{module:s}(void) {{\n"
            "#else\n"
            "PyMODINIT_FUNC init{module:s}(void) {{\n"
            "#endif\n"
            "    PyGILState_STATE gil_state;\n"
            "\n"
            "    PyObject *module = NULL;\n"
            "    PyObject *d = NULL;\n"
            "    PyObject *tmp = NULL;\n"
            "\n"
            "    /* Create the module\n"
            "     * This function must be called before grabbing the GIL\n"
            "     * otherwise the module will segfault on a version mismatch\n"
            "     */\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    module = PyModule_Create(\n"
            "        &{module:s}_module_definition );\n"
            "#else\n"
            "    module = Py_InitModule3(\n"
            "        \"{module:s}\",\n"
            "        {module:s}_module_methods,\n"
            "        \"Python {module:s} module.\" );\n"
            "#endif\n"
            "    if (module == NULL) {{\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        return(NULL);\n"
            "#else\n"
            "        return;\n"
            "#endif\n"
            "    }}\n"
            "    d = PyModule_GetDict(module);\n"
            "\n"
            "    /* Make sure threads are enabled */\n"
            "    PyEval_InitThreads();\n"
            "    gil_state = PyGILState_Ensure();\n"
            "\n"
            "    g_module = module;\n").format(**values_dict))

        # The trick is to initialise the classes in order of their
        # inheritance. The following code will order initializations
        # according to their inheritance tree
        done = set()
        for class_name in self.classes.keys():
            self.initialise_class(class_name, out, done)

        # Add the constants in here
        for constant, type in self.constants:
            if type == "integer":
                out.write(
                    "    tmp = PyLong_FromUnsignedLongLong((uint64_t) {0:s});\n".format(constant))
            elif type == "string":
                if constant == "TSK_VERSION_STR":
                    out.write((
                        "#if PY_MAJOR_VERSION >= 3\n"
                        "    tmp = PyUnicode_FromString((char *){0:s});\n"
                        "#else\n"
                        "    tmp = PyString_FromString((char *){0:s});\n"
                        "#endif\n").format(constant))

                else:
                    out.write((
                        "#if PY_MAJOR_VERSION >= 3\n"
                        "    tmp = PyBytes_FromString((char *){0:s});\n"
                        "#else\n"
                        "    tmp = PyString_FromString((char *){0:s});\n"
                        "#endif\n").format(constant))
            else:
                out.write(
                    "    /* I dont know how to convert {0:s} type {1:s} */\n".format(
                        constant, type))
                continue

            out.write((
                "    PyDict_SetItemString(d, \"{0:s}\", tmp);\n"
                "    Py_DecRef(tmp);\n").format(constant))

        out.write(self.initialization())
        out.write(
            "    PyGILState_Release(gil_state);\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "	return module;\n"
            "#else\n"
            "	return;\n"
            "#endif\n"
            "\n"
            "on_error:\n"
            "	PyGILState_Release(gil_state);\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "	return NULL;\n"
            "#else\n"
            "	return;\n"
            "#endif\n"
            "}\n")


class Type(object):
    interface = None
    buildstr = "O"
    sense = "IN"
    error_value = "return 0;"
    active = True

    def __init__(self, name, type, *args, **kwargs):
        super(Type, self).__init__()
        self.name = name
        self.type = type
        self.attributes = set()
        self.additional_args = kwargs

    def comment(self):
        return "{0:s} {1:s} ".format(self.type, self.name)

    def get_string(self):
        """Retrieves a string representation."""
        if self.name == "func_return":
            return self.type
        if "void" in self.type:
            return ""

        return "{0:s} : {1:s}".format(self.type, self.name)

    def python_name(self):
        return self.name

    def python_proxy_post_call(self):
        """This is called after a proxy call"""
        return ""

    def returned_python_definition(self, *arg, **kwargs):
        return self.definition(*arg, **kwargs)

    def definition(self, default=None, **kwargs):
        if default:
            return "{0:s} {1:s}={2:s};\n".format(
                self.type, self.name, default)
        elif "array_size" in self.additional_args:
            return (
                "int array_index = 0;\n"
                "{0:s} UNUSED *{1:s};\n").format(
                    self.type, self.name)
        else:
            return "{0:s} UNUSED {1:s};\n".format(
                self.type, self.name)

    def local_definition(self, default=None, **kwargs):
        return ""

    def byref(self):
        return "&{0:s}".format(self.name)

    def call_arg(self):
        return self.name

    def passthru_call(self):
        """Returns how we should call the function when simply passing args directly"""
        return self.call_arg()

    def pre_call(self, method, **kwargs):
        return ""

    def assign(self, call, method, target=None, **kwargs):
        return (
            "Py_BEGIN_ALLOW_THREADS\n"
            "{0:s} = {1:s};\n"
            "Py_END_ALLOW_THREADS\n").format(
                target or self.name, call)

    def post_call(self, method):
        # Check for errors
        result = (
            "if(check_error()) {\n"
            "    goto on_error;\n"
            "}\n")

        if "DESTRUCTOR" in self.attributes:
            result += "self->base = NULL;  //DESTRUCTOR - C object no longer valid\n"

        return result

    def from_python_object(self, source, destination, method, **kwargs):
        return ""

    def return_value(self, value):
        return "return {0!s};".format(value)


class String(Type):
    interface = "string"
    buildstr = "s"
    error_value = "return NULL;"

    def __init__(self, name, type, *args, **kwargs):
        super(String, self).__init__(name, type, *args, **kwargs)
        self.length = "strlen({0:s})".format(name)

    def byref(self):
        return "&{0:s}".format(self.name)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result}

        result = (
            "    PyErr_Clear();\n"
            "\n"
            "    if(!{name:s}) {{\n"
            "        Py_IncRef(Py_None);\n"
            "        {result:s} = Py_None;\n"
            "    }} else {{\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#else\n"
            "        {result:s} = PyString_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#endif\n"
            "        if(!{result:s}) {{\n"
            "            goto on_error;\n"
            "        }}\n"
            "    }}\n").format(**values_dict)

        if "BORROWED" not in self.attributes and "BORROWED" not in kwargs:
            result += "talloc_unlink(NULL, {0:s});\n".format(name)

        return result

    def from_python_object(self, source, destination, method, context="NULL"):
        method.error_set = True

        values_dict = {
            "context": context,
            "destination": destination,
            "source": source}

        return (
            "{{\n"
            "    char *buff = NULL;\n"
            "    Py_ssize_t length = 0;\n"
            "\n"
            "    PyErr_Clear();\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    if(PyBytes_AsStringAndSize({source:s}, &buff, &length) == -1) {{\n"
            "#else\n"
            "    if(PyString_AsStringAndSize({source:s}, &buff, &length) == -1) {{\n"
            "#endif\n"
            "        goto on_error;\n"
            "    }}\n"
            "    {destination:s} = talloc_size({context:s}, length + 1);\n"
            "    memcpy({destination:s}, buff, length);\n"
            "    {destination:s}[length] = 0;\n"
            "}};\n").format(**values_dict)


class ZString(String):
    interface = "null_terminated_string"


class BorrowedString(String):
    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#else\n"
            "    {result:s} = PyString_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#endif\n").format(**values_dict)


class Char_and_Length(Type):
    interface = "char_and_length"
    buildstr = "s#"
    error_value = "return NULL;"

    def __init__(self, data, data_type, length, length_type, *args, **kwargs):
        super(Char_and_Length, self).__init__(data, data_type, *args, **kwargs)

        self.name = data
        self.data_type = data_type
        self.length = length
        self.length_type = length_type

    def comment(self):
        return "{0:s} {1:s}, {2:s} {3:s}".format(
            self.data_type, self.name, self.length_type, self.length)

    def definition(self, default="\"\"", **kwargs):
        return (
            "char *{0:s}={1:s};\n"
            "Py_ssize_t {2:s}=strlen({3:s});\n").format(
                self.name, default, self.length, default)

    def byref(self):
        return "&{0:s}, &{1:s}".format(self.name, self.length)

    def call_arg(self):
        return "({0:s}){1:s}, ({2:s}){3:s}".format(
            self.data_type, self.name, self.length_type, self.length)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "length": self.length,
            "name": self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyBytes_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#else\n"
            "    {result:s} = PyString_FromStringAndSize((char *){name:s}, {length:s});\n"
            "#endif\n"
            "\n"
            "    if(!{result:s}) {{\n"
            "        goto on_error;\n"
            "    }}\n").format(**values_dict)


class Integer(Type):
    interface = "integer"
    buildstr = "i"
    int_type = "int"

    def __init__(self, name, type, *args, **kwargs):
        super(Integer, self).__init__(name, type, *args, **kwargs)
        self.type = self.int_type
        self.original_type = type

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyLong_FromLong({name:s});\n"
            "#else\n"
            "    {result:s} = PyInt_FromLong({name:s});\n"
            "#endif\n").format(**values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {destination:s} = PyLong_AsLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyInt_AsLongMask({source:s});\n"
            "#endif\n").format(**values_dict)

    def comment(self):
        return "{0:s} {1:s} ".format(self.original_type, self.name)


class IntegerUnsigned(Integer):
    buildstr = "I"
    int_type = "unsigned int"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        if "array_size" in self.additional_args:
            values_dict = {
                "name": name or self.name,
                "result": result,
                "array_size": self.additional_args["array_size"]
            }
            return (
                "    PyErr_Clear();\n"
                "    {result:s} = PyList_New(0);\n"
                "    for(array_index = 0; array_index < {array_size:s}; array_index++) {{\n"
                "#if PY_MAJOR_VERSION >= 3\n"
                "       PyList_Append({result:s}, PyLong_FromLong((long) {name:s}[array_index]));\n"
                "#else\n"
                "       PyList_Append({result:s}, PyInt_FromLong((long) {name:s}[array_index]));\n"
                "#endif\n"
                "    }}\n"
            ).format(**values_dict)
        else:
            values_dict = {
                "name": name or self.name,
                "result": result}
            return (
                "    PyErr_Clear();\n"
                "#if PY_MAJOR_VERSION >= 3\n"
                "    {result:s} = PyLong_FromLong((long) {name:s});\n"
                "#else\n"
                "    {result:s} = PyInt_FromLong((long) {name:s});\n"
                "#endif\n").format(**values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {destination:s} = PyLong_AsUnsignedLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyInt_AsUnsignedLongMask({source:s});\n"
            "#endif\n").format(**values_dict)


class Integer8(Integer):
    int_type = "int8_t"


class Integer8Unsigned(IntegerUnsigned):
    int_type = "uint8_t"


class Integer16(Integer):
    int_type = "int16_t"


class Integer16Unsigned(IntegerUnsigned):
    int_type = "uint16_t"


class Integer32(Integer):
    int_type = "int32_t"


class Integer32Unsigned(IntegerUnsigned):
    int_type = "uint32_t"


class Integer64(Integer):
    buildstr = "L"
    int_type = "int64_t"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {result:s} = PyLong_FromLongLong({name:s});\n"
            "#else\n"
            "    {result:s} = PyLong_FromLong({name:s});\n"
            "#endif\n").format(**values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {destination:s} = PyLong_AsLongLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyLong_AsLongMask({source:s});\n"
            "#endif\n"
            "#else\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {destination:s} = PyInt_AsLongLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyInt_AsLongMask({source:s});\n"
            "#endif\n"
            "#endif /* PY_MAJOR_VERSION >= 3 */\n").format(**values_dict)


class Integer64Unsigned(Integer):
    buildstr = "K"
    int_type = "uint64_t"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {result:s} = PyLong_FromUnsignedLongLong({name:s});\n"
            "#else\n"
            "    {result:s} = PyLong_FromUnsignedLong({name:s});\n"
            "#endif\n").format(**values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        # TODO: use integer_object_copy_to_uint64 instead to support both
        # long and int objects.
        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {destination:s} = PyLong_AsUnsignedLongLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyLong_AsUnsignedLongMask({source:s});\n"
            "#endif\n"
            "#else\n"
            "#if defined( HAVE_LONG_LONG )\n"
            "    {destination:s} = PyInt_AsUnsignedLongLongMask({source:s});\n"
            "#else\n"
            "    {destination:s} = PyInt_AsUnsignedLongMask({source:s});\n"
            "#endif\n"
            "#endif /* PY_MAJOR_VERSION >= 3 */\n").format(**values_dict)


class Long(Integer):
    buildstr = "l"
    int_type = "long"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "PyErr_Clear();\n"
            "{result:s} = PyLong_FromLongLong({name:s});\n").format(
                **values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "PyErr_Clear();\n"
            "{destination:s} = PyLong_AsLongMask({source:s});\n").format(
                **values_dict)


class LongUnsigned(Integer):
    buildstr = "k"
    int_type = "unsigned long"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "PyErr_Clear();\n"
            "{result:s} = PyLong_FromUnsignedLong({name:s});\n").format(
                **values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "PyErr_Clear();\n"
            "{destination:s} = PyLong_AsUnsignedLongMask({source:s});\n").format(
                **values_dict)


class Char(Integer):
    buildstr = "s"
    interface = "small_integer"

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        # We really want to return a string here
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "{{\n"
            "    char *str_{name:s} = &{name:s};\n"
            "\n"
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyBytes_FromStringAndSize(str_{name:s}, 1);\n"
            "#else\n"
            "    {result:s} = PyString_FromStringAndSize(str_{name:s}, 1);\n"
            "#endif\n"
            "\n"
            "    if(!{result:s}) {{\n"
            "        goto on_error;\n"
            "}}\n").format(**values_dict)

    def definition(self, default="\"\\x0\"", **kwargs):
        # Shut up unused warnings
        return (
            "char {0:s} UNUSED=0;\n"
            "char *str_{0:s} UNUSED = {1:s};\n").format(
                self.name, default)

    def byref(self):
        return "&str_{0:s}".format(self.name)

    def pre_call(self, method, **kwargs):
        method.error_set = True

        values_dict = {
            "name": self.name}

        return (
            "    if(strlen(str_{name:s}) != 1) {\n"
            "        PyErr_Format(PyExc_RuntimeError, \"You must only provide a single character for arg {name:s}\");\n"
            "        goto on_error;\n"
            "    }\n"
            "\n"
            "    {name:s} = str_{name:s}[0];\n").format(
                **values_dict)


class StringOut(String):
    sense = "OUT"


class IntegerOut(Integer):
    """Handle Integers pushed out through OUT int *result."""
    sense = "OUT_DONE"
    buildstr = ""
    int_type = "int *"

    def definition(self, default=0, **kwargs):
        # We need to make static storage for the pointers
        storage = "storage_{0:s}".format(self.name)
        bare_type = self.type.split()[0]
        type_definition = Type.definition(
            self, "&{0:s}".format(storage))

        return (
            "{0:s} {1:s} = 0;\n"
            "{2:s}\n").format(
                bare_type, storage, type_definition)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "PyErr_Clear();\n"
            "{result:s} = PyLong_FromLongLong(*{name:s});\n").format(
                **values_dict)

    def python_name(self):
        return None

    def byref(self):
        return self.name

    def call_arg(self):
        return "{0:s}".format(self.name)

    def passthru_call(self):
        return self.name


class PInteger32UnsignedOut(IntegerOut):
    buildstr = ""
    int_type = "uint32_t *"


class PInteger64UnsignedOut(IntegerOut):
    buildstr = ""
    int_type = "uint64_t *"


class Char_and_Length_OUT(Char_and_Length):
    sense = "OUT_DONE"
    buildstr = "l"

    def definition(self, default=0, **kwargs):
        values_dict = {
            "default": default,
            "length": self.length,
            "name": self.name}

        return (
            "    char *{name:s} = NULL;\n"
            "    Py_ssize_t {length:s} = {default:d};\n"
            "    PyObject *tmp_{name:s} = NULL;\n").format(
                **values_dict)

    def error_cleanup(self):
        values_dict = {
            "name": self.name}

        return (
            "    if(tmp_{name:s} != NULL) {{\n"
            "        Py_DecRef(tmp_{name:s});\n"
            "    }}\n").format(**values_dict)

    def python_name(self):
        return self.length

    def byref(self):
        return "&{0:s}".format(self.length)

    def pre_call(self, method, **kwargs):
        values_dict = {
            "length": self.length,
            "name": self.name}

        return (
            "    PyErr_Clear();\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    tmp_{name:s} = PyBytes_FromStringAndSize(NULL, {length:s});\n"
            "#else\n"
            "    tmp_{name:s} = PyString_FromStringAndSize(NULL, {length:s});\n"
            "#endif\n"
            "    if(!tmp_{name:s}) {{\n"
            "        goto on_error;\n"
            "    }}\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    PyBytes_AsStringAndSize(tmp_{name:s}, &{name:s}, (Py_ssize_t *)&{length:s});\n"
            "#else\n"
            "    PyString_AsStringAndSize(tmp_{name:s}, &{name:s}, (Py_ssize_t *)&{length:s});\n"
            "#endif\n").format(**values_dict)

    def to_python_object(self, name=None, result="Py_result", sense="in", **kwargs):
        if "results" in kwargs:
            kwargs["results"].pop(0)

        if sense == "proxied":
            return "py_{0:s} = PyLong_FromLong({1:s});\n".format(
                self.name, self.length)

        values_dict = {
            "length": self.length,
            "name": name or self.name,
            "result": result}

        return (
            "    /* NOTE - this should never happen\n"
            "     * it might indicate an overflow condition.\n"
            "     */\n"
            "    if(func_return > {length:s}) {{\n"
            "        printf(\"Programming Error - possible overflow!!\\n\");\n"
            "        abort();\n"
            "\n"
            "    // Do we need to truncate the buffer for a short read?\n"
            "    }} else if(func_return < {length:s}) {{\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        _PyBytes_Resize(&tmp_{name:s}, (Py_ssize_t)func_return);\n"
            "#else\n"
            "        _PyString_Resize(&tmp_{name:s}, (Py_ssize_t)func_return);\n"
            "#endif\n"
            "    }}\n"
            "\n"
            "    {result:s} = tmp_{name:s};\n").format(**values_dict)

    def python_proxy_post_call(self, result="Py_result"):
        values_dict = {
            "name": self.name,
            "result": result}

        return (
            "{{\n"
            "    char *tmp_buff = NULL;\n"
            "    Py_ssize_t tmp_len = 0;\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    if(PyBytes_AsStringAndSize({result:s}, &tmp_buff, &tmp_len) == -1) {{\n"
            "#else\n"
            "    if(PyString_AsStringAndSize({result:s}, &tmp_buff, &tmp_len) == -1) {{\n"
            "#endif\n"
            "        goto on_error;\n"
            "    }}\n"
            "    memcpy({name:s}, tmp_buff, tmp_len);\n"
            "    Py_DecRef({result:s});\n"
            "    {result:s} = PyLong_FromLong(tmp_len);\n"
            "}}\n").format(**values_dict)


class TDB_DATA_P(Char_and_Length_OUT):
    bare_type = "TDB_DATA"

    def __init__(self, name, type, *args, **kwargs):
        super(TDB_DATA_P, self).__init__(name, type, *args, **kwargs)

    def definition(self, default=None, **kwargs):
        return Type.definition(self)

    def byref(self):
        return "{0:s}.dptr, &{0:s}.dsize".format(self.name)

    def pre_call(self, method, **kwargs):
        return ""

    def call_arg(self):
        return Type.call_arg(self)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyBytes_FromStringAndSize((char *){name:s}->dptr, {name:s}->dsize);\n"
            "#else\n"
            "    {result:s} = PyString_FromStringAndSize((char *){name:s}->dptr, {name:s}->dsize);\n"
            "#endif\n"
            "    talloc_free({name:s});\n").format(**values_dict)

    def from_python_object(self, source, destination, method, **kwargs):
        method.error_set = True
        values_dict = {
            "bare_type": self.bare_type,
            "destination": destination,
            "source": source}

        return (
            "{destination:s} = talloc_zero(self, {bare_type:s});\n"
            "{{\n"
            "    char *buf = NULL;\n"
            "    Py_ssize_t tmp = 0;\n"
            "\n"
            "    PyErr_Clear();\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    if(PyBytes_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{\n"
            "#else\n"
            "    if(PyString_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{\n"
            "#endif\n"
            "        goto on_error;\n"
            "    }}\n"
            "\n"
            "    // Take a copy of the Python string\n"
            "    {destination:s}->dptr = talloc_memdup({destination:s}, buf, tmp);\n"
            "    {destination:s}->dsize = tmp;\n"
            "}}\n"
            "// We no longer need the Python object\n"
            "Py_DecRef({source:s});\n").format(**values_dict)


class TDB_DATA(TDB_DATA_P):
    error_value = (
        "{result:s}.dptr = NULL;\n"
        "return {result:s};")

    def from_python_object(self, source, destination, method, **kwargs):
        method.error_set = True
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "{{\n"
            "    char *buf = NULL;\n"
            "    Py_ssize_t tmp = 0;\n"
            "\n"
            "    PyErr_Clear();\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    if(PyBytes_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{\n"
            "#else\n"
            "    if(PyString_AsStringAndSize({source:s}, &buf, &tmp) == -1) {{\n"
            "#endif\n"
            "        goto on_error;\n"
            "    }}\n"
            "    // Take a copy of the Python string - This leaks - how to fix it?\n"
            "    {destination:s}.dptr = talloc_memdup(NULL, buf, tmp);\n"
            "    {destination:s}.dsize = tmp;\n"
            "}}\n"
            "// We no longer need the Python object\n"
            "Py_DecRef({source:s});\n").format(**values_dict)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "    PyErr_Clear();\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    {result:s} = PyBytes_FromStringAndSize((char *){name:s}.dptr, {name:s}.dsize);\n"
            "#else\n"
            "    {result:s} = PyString_FromStringAndSize((char *){name:s}.dptr, {name:s}.dsize);\n"
            "#endif\n").format(**values_dict)


class Void(Type):
    buildstr = ""
    error_value = "return;"
    original_type = ""

    def __init__(self, name, type="void", *args, **kwargs):
        super(Void, self).__init__(name, type, *args, **kwargs)

    def comment(self):
        return "void *ctx"

    def definition(self, default=None, **kwargs):
        return ""

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        return (
            "Py_IncRef(Py_None);\n"
            "Py_result = Py_None;\n")

    def call_arg(self):
        return "NULL"

    def byref(self):
        return None

    def assign(self, call, method, target=None, **kwargs):
        # We don't assign the result to anything.
        return (
            "    Py_BEGIN_ALLOW_THREADS\n"
            "    (void) {0:s};\n"
            "    Py_END_ALLOW_THREADS\n").format(call)

    def return_value(self, value):
        return "return;"


class PVoid(Void):
    def __init__(self, name, type="void *", *args, **kwargs):
        super(PVoid, self).__init__(name, type, *args, **kwargs)


class StringArray(String):
    interface = "array"
    buildstr = "O"

    def definition(self, default="\"\"", **kwargs):
        return (
            "char **{0:s} = NULL;\n"
            "PyObject *py_{0:s} = NULL;\n").format(self.name)

    def byref(self):
        return "&py_{0:s}".format(self.name)

    def from_python_object(self, source, destination, method, context="NULL"):
        method.error_set = True
        values_dict = {
            "destination": destination,
            "source": source}

        return (
            "{{\n"
            "    Py_ssize_t i = 0;\n"
            "    Py_ssize_t size = 0;\n"
            "\n"
            "    if({source:s}) {{\n"
            "        if(!PySequence_Check({source:s})) {{\n"
            "            PyErr_Format(PyExc_ValueError, \"{destination:s} must be a sequence\");\n"
            "            goto on_error;\n"
            "        }}\n"
            "        size = PySequence_Size({source:s});\n"
            "    }}\n"
            "    {destination:s} = talloc_zero_array(NULL, char *, size + 1);\n"
            "\n"
            "    for(i = 0; i < size; i++) {{\n"
            "        PyObject *tmp = PySequence_GetItem({source:s}, i);\n"
            "        if(!tmp) {{\n"
            "            goto on_error;\n"
            "        }}\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        {destination:s}[i] = PyBytes_AsString(tmp);\n"
            "#else\n"
            "        {destination:s}[i] = PyString_AsString(tmp);\n"
            "#endif\n"
            "\n"
            "        if(!{destination:s}[i]) {{\n"
            "            Py_DecRef(tmp);\n"
            "            goto on_error;\n"
            "        }}\n"
            "        Py_DecRef(tmp);\n"
            "    }}\n"
            "}}\n").format(**values_dict)

    def pre_call(self, method, **kwargs):
        return self.from_python_object(
            "py_{0:s}".format(self.name), self.name, method)

    def error_condition(self):
        return (
            "    if({0:s}) {{\n"
            "        talloc_free({0:s});\n"
            "    }}\n").format(self.name)


class Wrapper(Type):
    """This class represents a wrapped C type """
    sense = "IN"
    error_value = "return NULL;"

    def from_python_object(self, source, destination, method, **kwargs):
        values_dict = {
            "destination": destination,
            "source": source,
            "type": self.type}

        return (
            "     /* First check that the returned value is in fact a Wrapper */\n"
            "     if(!type_check({source:s}, &{type:s}_Type)) {{\n"
            "          PyErr_Format(PyExc_RuntimeError, \"function must return an {type:s} instance\");\n"
            "          goto on_error;\n"
            "     }}\n"
            "\n"
            "     {destination:s} = ((Gen_wrapper) {source:s})->base;\n"
            "\n"
            "     if(!{destination:s}) {{\n"
            "          PyErr_Format(PyExc_RuntimeError, \"{type:s} instance is no longer valid (was it gc'ed?)\");\n"
            "          goto on_error;\n"
            "}}\n"
            "\n").format(**values_dict)

    def to_python_object(self, **kwargs):
        return ""

    def returned_python_definition(self, default="NULL", sense="in", **kwargs):
        return "{0:s} {1:s} = {2:s};\n".format(
            self.type, self.name, default)

    def byref(self):
        return "&wrapped_{0:s}".format(self.name)

    def definition(self, default="NULL", sense="in", **kwargs):
        result = "    Gen_wrapper wrapped_{0:s} UNUSED = {1:s};\n".format(
            self.name, default)

        if sense == "in" and not "OUT" in self.attributes:
            result += "    {0:s} UNUSED {1:s};\n".format(
                self.type, self.name)

        return result

    def call_arg(self):
        return "{0:s}".format(self.name)

    def pre_call(self, method, python_object_index=1, **kwargs):
        if "OUT" in self.attributes or self.sense == "OUT":
            return ""
        self.original_type = self.type.split()[0]

        values_dict = {
            "name": self.name,
            "original_type": self.original_type,
            "python_object_index": python_object_index}

        return (
            "    if(wrapped_{name:s} == NULL || (PyObject *)wrapped_{name:s} == Py_None) {{\n"
            "        {name:s} = NULL;\n"
            "    }} else if(!type_check((PyObject *)wrapped_{name:s},&{original_type:s}_Type)) {{\n"
            "        PyErr_Format(PyExc_RuntimeError, \"{name:s} must be derived from type {original_type:s}\");\n"
            "        goto on_error;\n"
            "    }} else if(wrapped_{name:s}->base == NULL) {{\n"
            "        PyErr_Format(PyExc_RuntimeError, \"{original_type:s} instance is no longer valid (was it gc'ed?)\");\n"
            "        goto on_error;\n"
            "    }} else {{\n"
            "        {name:s} = wrapped_{name:s}->base;\n"
            "        if(self->python_object{python_object_index:d} == NULL) {{\n"
            "            self->python_object{python_object_index:d} = (PyObject *) wrapped_{name:s};\n"
            "            Py_IncRef(self->python_object{python_object_index:d});\n"
            "        }}\n"
            "    }}\n").format(**values_dict)

    def assign(self, call, method, target=None, **kwargs):
        method.error_set = True;

        values_dict = {
            "call": call.strip(),
            "incref": INCREF,
            "name": target or self.name,
            "type": self.type}

        result = (
            "    {{\n"
            "        Object returned_object = NULL;\n"
            "\n"
            "        ClearError();\n"
            "\n"
            "        Py_BEGIN_ALLOW_THREADS\n"
            "        // This call will return a Python object if the base is a proxied Python object\n"
            "        // or a talloc managed object otherwise.\n"
            "        returned_object = (Object) {call:s};\n"
            "        Py_END_ALLOW_THREADS\n"
            "\n"
            "        if(check_error()) {{\n"
            "            if(returned_object != NULL) {{\n"
            "                if(self->base_is_python_object != 0) {{\n"
            "                    Py_DecRef((PyObject *) returned_object);\n"
            "                }} else if(self->base_is_internal != 0) {{\n"
            "                    talloc_free(returned_object);\n"
            "                }}\n"
            "            }}\n"
            "            goto on_error;\n"
            "        }}\n").format(**values_dict)

        # Is NULL an acceptable return type? In some Python code NULL
        # can be returned (e.g. in iterators) but usually it should
        # be converted to Py_None.
        if "NULL_OK" in self.attributes:
            result += (
                "        if(returned_object == NULL) {\n"
                "            goto on_error;\n"
                "        }\n")

        result += (
            "        wrapped_{name:s} = new_class_wrapper(returned_object, self->base_is_python_object);\n"
            "\n"
            "        if(wrapped_{name:s} == NULL) {{\n"
            "            if(returned_object != NULL) {{\n"
            "                if(self->base_is_python_object != 0) {{\n"
            "                    Py_DecRef((PyObject *) returned_object);\n"
            "                }} else if(self->base_is_internal != 0) {{\n"
            "                    talloc_free(returned_object);\n"
            "                }}\n"
            "            }}\n"
            "            goto on_error;\n"
            "        }}\n").format(**values_dict)

        if "BORROWED" in self.attributes:
            result += (
                "        #error unchecked BORROWED code segment\n"
                "        {incref:s}(wrapped_{name:s}->base);\n"
                "        if(((Object) wrapped_{name:s}->base)->extension) {{\n"
                "            Py_IncRef((PyObject *) ((Object) wrapped_{name:s}->base)->extension);\n"
                "        }}\n").format(**values_dict)

        result += (
            "    }\n")

        return result

    def to_python_object(
            self, name=None, result="Py_result", sense="in", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        if sense == "proxied":
            return (
                "{result:s} = (PyObject *) new_class_wrapper((Object){name:s}, 0);\n").format(
                    **values_dict)

        return "{result:s} = (PyObject *) wrapped_{name:s};\n".format(
            **values_dict)


class PointerWrapper(Wrapper):
    """ A pointer to a wrapped class """

    def __init__(self, name, type, *args, **kwargs):
        type = type.split()[0]
        super(PointerWrapper, self).__init__(name, type, *args, **kwargs)

    def comment(self):
        return "{0:s} *{1:s}".format(self.type, self.name)

    def definition(self, default="NULL", sense="in", **kwargs):
        result = "Gen_wrapper wrapped_{0:s} = {1:s};".format(
            self.name, default)
        if sense == "in" and not "OUT" in self.attributes:
            result += " {0:s} *{1:s};\n".format(self.type, self.name)

        return result

    def byref(self):
        return "&wrapped_{0:s}".format(self.name)

    def pre_call(self, method, **kwargs):
        if "OUT" in self.attributes or self.sense == "OUT":
            return ""
        self.original_type = self.type.split()[0]
        values_dict = {
            "name": self.name,
            "original_type": self.original_type}

        return (
            "if(!wrapped_{name:s} || (PyObject *)wrapped_{name:s}==Py_None) {{\n"
            "   {name:s} = NULL;\n"
            "}} else if(!type_check((PyObject *)wrapped_{name:s},&{original_type:s}_Type)) {{\n"
            "     PyErr_Format(PyExc_RuntimeError, \"{name:s} must be derived from type {original_type:s}\");\n"
            "     goto on_error;\n"
            "}} else {{\n"
            "   {name:s} = ({original_type:s} *)&wrapped_{name:s}->base;\n"
            "}};\n").format(**values_dict)


class StructWrapper(Wrapper):
    """ A wrapper for struct classes """
    active = False

    def __init__(self, name, type, *args, **kwargs):
        super(StructWrapper, self).__init__(name, type, *args, **kwargs)
        self.original_type = type.split()[0]

    def assign(self, call, method, target=None, borrowed=True, **kwargs):
        self.original_type = self.type.split()[0]
        values_dict = {
            "call": call.strip(),
            "name": target or self.name,
            "type": self.original_type}

        result = (
            "\n"
            "        PyErr_Clear();\n"
            "\n"
            "        wrapped_{name:s} = (Gen_wrapper) PyObject_New(py{type:s}, &{type:s}_Type);\n"
            "\n").format(**values_dict)

        if borrowed:
            result += (
                "        // Base is borrowed from another object.\n"
                "        wrapped_{name:s}->base = {call:s};\n"
                "        wrapped_{name:s}->base_is_python_object = 0;\n"
                "        wrapped_{name:s}->base_is_internal = 0;\n"
                "        wrapped_{name:s}->python_object1 = NULL;\n"
                "        wrapped_{name:s}->python_object2 = NULL;\n"
                "\n").format(**values_dict)
        else:
            result += (
                "        wrapped_{name:s}->base = {call:s};\n"
                "        wrapped_{name:s}->base_is_python_object = 0;\n"
                "        wrapped_{name:s}->base_is_internal = 1;\n"
                "        wrapped_{name:s}->python_object1 = NULL;\n"
                "        wrapped_{name:s}->python_object2 = NULL;\n"
                "\n").format(**values_dict)

        if "NULL_OK" in self.attributes:
            result += (
                "        if(wrapped_{name:s}->base == NULL) {{\n"
                "             Py_DecRef((PyObject *) wrapped_{name:s});\n"
                "             return NULL;\n"
                "        }}\n").format(**values_dict)

        result += (
            "        // A NULL object gets translated to a None\n"
            "        if(wrapped_{name:s}->base == NULL) {{\n"
            "            Py_DecRef((PyObject *) wrapped_{name:s});\n"
            "            Py_IncRef(Py_None);\n"
            "            wrapped_{name:s} = (Gen_wrapper) Py_None;\n"
            "        }}\n").format(**values_dict)

        # TODO: with the following code commented out is makes no sense to have the else clause here.
        #   "    }} else {{\n").format(**values_dict)

        # if "FOREIGN" in self.attributes:
        #     result += "// Not taking references to foreign memory\n"
        # elif "BORROWED" in self.attributes:
        #     result += "talloc_reference({name:s}->ctx, {name:s}->base);\n".format(**values_dict)
        # else:
        #     result += "talloc_steal({name:s}->ctx, {name:s}->base);\n".format(**values_dict)
        # result += "}}\n"

        return result

    def byref(self):
        return "&{0:s}".format(self.name)

    def definition(self, default="NULL", sense="in", **kwargs):
        result = "Gen_wrapper wrapped_{0:s} = {1:s};".format(
            self.name, default)
        if sense == "in" and not "OUT" in self.attributes:
            result += " {0:s} *{1:s} = NULL;\n".format(
                self.original_type, self.name)

        return result;


class PointerStructWrapper(StructWrapper):
    def from_python_object(self, source, destination, method, **kwargs):
        return "{0:s} = ((Gen_wrapper) {1:s})->base;\n".format(
            destination, source)

    def byref(self):
        return "&wrapped_{0:s}".format(self.name)


class Timeval(Type):
    """Handle struct timeval values."""
    interface = "numeric"
    buildstr = "f"

    def definition(self, default=None, **kwargs):
        return (
            "struct timeval {0:s};\n".format(self.name) +
            self.local_definition(default, **kwargs))

    def local_definition(self, default=None, **kwargs):
        return "float {0:s}_flt;\n".format(self.name)

    def byref(self):
        return "&{0:s}_flt".format(self.name)

    def pre_call(self, method, **kwargs):
        return (
            "{0:s}.tv_sec = (int){0:s}_flt;\n"
            "{0:s}.tv_usec = ({0:s}_flt - {0:s}.tv_sec) * 1e6;\n").format(
                self.name)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        values_dict = {
            "name": name or self.name,
            "result": result}

        return (
            "{name:s}_flt = (double)({name:s}.tv_sec) + {name:s}.tv_usec;\n"
            "{result:s} = PyFloat_FromDouble({name:s}_flt);\n").format(
                **values_dict)


class PyObject(Type):
    """Accept an opaque Python object."""
    interface = "opaque"
    buildstr = "O"

    def definition(self, default="NULL", **kwargs):
        self.default = default
        values_dict = {
            "default": self.default,
            "name": self.name}

        return (
            "PyObject *{name:s} = {default:s};\n").format(
                **values_dict)

    def byref(self):
        return "&{0:s}".format(self.name)


type_dispatcher = {
    "IN unsigned char *": String,
    "IN char *": String,

    "unsigned char *": String,
    "char *": String,

    "ZString": ZString,

    "OUT unsigned char *": StringOut,
    "OUT char *": StringOut,

    "OUT uint64_t *": PInteger64UnsignedOut,
    "OUT uint32_t *": PInteger32UnsignedOut,

    "void *": PVoid,
    "void": Void,

    "TDB_DATA *": TDB_DATA_P,
    "TDB_DATA": TDB_DATA,
    "TSK_INUM_T": Integer,

    "off_t": Integer64,
    "size_t": Integer64Unsigned,
    "ssize_t": Integer64,
    "time_t": Integer64,

    "unsigned long": LongUnsigned,
    "long": Long,
    "unsigned long int": LongUnsigned,
    "long int": Integer,
    "unsigned int": Integer,
    "int": Integer,

    "uint64_t": Integer64Unsigned,
    "uint32_t": Integer32Unsigned,
    "uint16_t": Integer16Unsigned,
    "uint8_t": Integer8Unsigned,
    "int64_t": Integer64,
    "int32_t": Integer32,
    "int16_t": Integer16,
    "int8_t": Integer8,
    "char": Char,

    "struct timeval": Timeval,
    "char **": StringArray,
    "PyObject *": PyObject,
}

method_attributes = ["BORROWED", "DESTRUCTOR", "IGNORE"]


class ResultException(object):
    value = 0
    exception = "PyExc_IOError"

    def __init__(self, check, exception, message):
        self.check = check
        self.exception = exception
        self.message = message

    def write(self, out):
        out.write((
            "\n"
            "/* Handle exceptions */\n"
            "if({0:s}) {{\n"
            "    PyErr_Format(PyExc_{1:s}, {2:s});\n"
            "    goto on_error;\n"
            "}}\n"
            "\n").format(self.check, self.exception, self.message))


class Method(object):
    default_re = re.compile("DEFAULT\(([A-Z_a-z0-9]+)\) =(.+);")
    exception_re = re.compile("RAISES\(([^,]+),\s*([^\)]+)\) =(.+);")
    typedefed_re = re.compile(r"struct (.+)_t \*")

    def __init__(
        self, class_name, base_class_name, name, args, return_type,
        myclass=None):
        if not isinstance(myclass, ClassGenerator):
            raise RuntimeError("myclass must be a class generator")

        self.args = []
        self.base_class_name = base_class_name
        self.class_name = class_name
        self.defaults = {}
        self.definition_class_name = class_name
        self.docstring = ""
        self.error_set = False
        self.exception = None
        self.name = name
        self.myclass = myclass

        for type, name in args:
            self.add_arg(type, name)

        try:
            self.return_type = dispatch("func_return", return_type)
            self.return_type.attributes.add("OUT")
            self.return_type.original_type = return_type
        except KeyError:
            # Is it a wrapped type?
            if return_type:
                log("Unable to handle return type {0:s}.{1:s} {2:s}".format(
                    self.class_name, self.name, return_type))
                # pdb.set_trace()
            self.return_type = PVoid("func_return")

    def get_string(self):
        """Retrieves a string representation."""
        return "def {0:s} {1:s}({2:s}):".format(
            self.return_type.get_string(), self.name,
            " , ".join([a.get_string() for a in self.args]))

    def clone(self, new_class_name):
        self.find_optional_vars()

        result = self.__class__(
            new_class_name, self.base_class_name, self.name, [], "void *",
            myclass=self.myclass)
        result.args = self.args
        result.return_type = self.return_type
        result.definition_class_name = self.definition_class_name
        result.defaults = self.defaults
        result.exception = self.exception

        return result

    def find_optional_vars(self):
        for line in self.docstring.splitlines():
            m = self.default_re.search(line)
            if m:
                name = m.group(1)
                value = m.group(2)
                log("Setting default value for {0:s} of {1:s}".format(
                    m.group(1), m.group(2)))
                self.defaults[name] = value

            m = self.exception_re.search(line)
            if m:
                self.exception = ResultException(
                    m.group(1), m.group(2), m.group(3))

    def write_local_vars(self, out):
        self.find_optional_vars()

        # We do it in two passes - first mandatory then optional
        kwlist = "    static char *kwlist[] = {"
        # Mandatory
        for type in self.args:
            python_name = type.python_name()
            if python_name and python_name not in self.defaults:
                kwlist += "\"{0:s}\",".format(python_name)

        for type in self.args:
            python_name = type.python_name()
            if python_name and python_name in self.defaults:
                kwlist += "\"{0:s}\",".format(python_name)

        kwlist += " NULL};\n"

        for type in self.args:
            out.write(
                "    // DEBUG: local arg type: {0:s}\n".format(
                    type.__class__.__name__))
            python_name = type.python_name()
            try:
                out.write(type.definition(default=self.defaults[python_name]))
            except KeyError:
                out.write(type.definition())

        # Make up the format string for the parse args in two pases
        parse_line = ""
        for type in self.args:
            python_name = type.python_name()
            if type.buildstr and python_name not in self.defaults:
                parse_line += type.buildstr

        optional_args = ""
        for type in self.args:
            python_name = type.python_name()
            if type.buildstr and python_name in self.defaults:
                optional_args += type.buildstr

        if optional_args:
            parse_line += "|" + optional_args

        # Iterators have a different prototype and do not need to
        # unpack any args
        if not "iternext" in self.name:
            # Now parse the args from Python objects
            out.write("\n")
            out.write(kwlist)
            out.write((
                "\n"
                "    if(!PyArg_ParseTupleAndKeywords(args, kwds, \"{0:s}\", ").format(
                    parse_line))

            tmp = ["kwlist"]
            for type in self.args:
                ref = type.byref()
                if ref:
                    tmp.append(ref)

            out.write(",".join(tmp))
            self.error_set = True
            out.write(
                ")) {\n"
                "        goto on_error;\n"
                "    }\n")

    def error_condition(self):
        result = ""
        if "DESTRUCTOR" in self.return_type.attributes:
            result += "self->base = NULL;\n"

        if hasattr(self, "args"):
            for type in self.args:
                if hasattr(type, "error_cleanup"):
                    result += type.error_cleanup()

        result += "    return NULL;\n";
        return result

    def write_definition(self, out):
        out.write(
            "\n"
            "/********************************************************\n"
            "Autogenerated wrapper for function:\n")
        out.write(self.comment())
        out.write("********************************************************/\n")

        self._prototype(out)
        out.write((
            "{{\n"
            "    PyObject *returned_result = NULL;\n"
            "    PyObject *Py_result = NULL;\n"
            "\n"
            "    // DEBUG: return type: {0:s}\n"
            "    ").format(
                self.return_type.__class__.__name__))

        out.write(self.return_type.definition())

        self.write_local_vars(out)

        values_dict = {
            "class_name": self.class_name,
            "method": self.name}

        out.write((
            "\n"
            "    // Make sure that we have something valid to wrap\n"
            "    if(self->base == NULL) {{\n"
            "        return PyErr_Format(PyExc_RuntimeError, \"{class_name:s} object no longer valid\");\n"
            "    }}\n"
            "\n").format(**values_dict))

        # Precall preparations
        out.write("    // Precall preparations\n")
        out.write(self.return_type.pre_call(self))
        for type in self.args:
            out.write(type.pre_call(self))

        values_dict = {
            "class_name": self.class_name,
            "def_class_name": self.definition_class_name,
            "method": self.name}

        out.write((
            "    // Check the function is implemented\n"
            "    {{\n"
            "        void *method = (({def_class_name:s}) self->base)->{method:s};\n"
            "\n"
            "        if(method == NULL || (void *) unimplemented == (void *) method) {{\n"
            "            PyErr_Format(PyExc_RuntimeError, \"{class_name:s}.{method:s} is not implemented\");\n"
            "            goto on_error;\n"
            "        }}\n"
            "\n"
            "        // Make the call\n"
            "        ClearError();\n").format(**values_dict))

        base = "(({0:s}) self->base)".format(self.definition_class_name)
        call = "        {0:s}->{1:s}({2:s}".format(base, self.name, base)
        tmp = ""
        for type in self.args:
            tmp += ", " + type.call_arg()

        call += "{0:s})".format(tmp)

        # Now call the wrapped function
        out.write(self.return_type.assign(call, self, borrowed=False))
        if self.exception:
            self.exception.write(out)

        self.error_set = True

        out.write(
            "    };\n"
            "\n"
            "    // Postcall preparations\n")
        # Postcall preparations
        post_calls = []

        post_call = self.return_type.post_call(self)
        post_calls.append(post_call)
        out.write("    {0:s}".format(post_call))

        for type in self.args:
            post_call = type.post_call(self)
            if post_call not in post_calls:
                post_calls.append(post_call)
                out.write("    {0:s}".format(post_call))

        # Now assemble the results
        results = [self.return_type.to_python_object()]
        for type in self.args:
            if type.sense == "OUT_DONE":
                results.append(type.to_python_object(results=results))

        # If all the results are returned by reference we dont need
        # to prepend the void return value at all.
        if isinstance(self.return_type, Void) and len(results) > 1:
            results.pop(0)

        out.write(
            "\n"
            "    // prepare results\n")
        # Make a tuple of results and pass them back
        if len(results) > 1:
            out.write("returned_result = PyList_New(0);\n")
            for result in results:
                out.write(result)
                out.write(
                    "PyList_Append(returned_result, Py_result);\n"
                    "Py_DecRef(Py_result);\n")
            out.write("return returned_result;\n")
        else:
            out.write(results[0])
            # This useless code removes compiler warnings
            out.write(
                "    returned_result = Py_result;\n"
                "    return returned_result;\n")

        # Write the error part of the function
        if self.error_set:
            out.write((
                "\n"
                "on_error:\n"
                "{0:s}").format(self.error_condition()))

        out.write("};\n\n")

    def add_arg(self, type, name):
        try:
            t = type_dispatcher[type](name, type)
        except KeyError:
            # Sometimes types must be typedefed in advance
            try:
                m = self.typedefed_re.match(type)
                type = m.group(1)
                log("Trying {0:s} for {1:s}".format(type, m.group(0)))
                t = type_dispatcher[type](name, type)
            except (KeyError, AttributeError):
                log("Unable to handle type {0:s}.{1:s} {2:s}".format(
                    self.class_name, self.name, type))
                return

        # Here we collapse char * + int type interfaces into a
        # coherent string like interface.
        try:
            previous = self.args[-1]
            if t.interface == "integer" and previous.interface == "string":

                # We make a distinction between IN variables and OUT
                # variables
                if previous.sense == "OUT":
                    cls = Char_and_Length_OUT
                else:
                    cls = Char_and_Length

                cls = cls(
                    previous.name,
                    previous.type,
                    name, type)

                self.args[-1] = cls

                return
        except IndexError:
            pass

        self.args.append(t)

    def comment(self):
        args = []
        for type in self.args:
            args.append(type.comment())

        return "{0:s} {1:s}.{2:s}({3:s});\n".format(
            self.return_type.original_type, self.class_name, self.name,
            ",".join(args))

    def prototype(self, out):
        self._prototype(out)
        out.write(";\n")

    def _prototype(self, out):
        values_dict = {
            "class_name": self.class_name,
            "method": self.name}

        out.write(
            "static PyObject *py{class_name:s}_{method:s}(py{class_name:s} *self, PyObject *args, PyObject *kwds)".format(
                **values_dict))

    def PyMethodDef(self, out):
        docstring = self.comment() + "\n\n" + self.docstring.strip()
        values_dict = {
            "class_name": self.class_name,
            "docstring": format_as_docstring(docstring),
            "name": self.name}

        out.write((
            "    {{ \"{name:s}\",\n"
            "      (PyCFunction) py{class_name:s}_{name:s},\n"
            "      METH_VARARGS|METH_KEYWORDS,\n"
            "      \"{docstring:s}\" }},\n"
            "\n").format(**values_dict))


class IteratorMethod(Method):
    """A method which implements an iterator."""

    def __init__(self, *args, **kwargs):
        super(IteratorMethod, self).__init__(*args, **kwargs)

        # Tell the return type that a NULL Python return is ok
        self.return_type.attributes.add("NULL_OK")

    def get_string(self):
        """Retrieves a string representation."""
        return "Iterator returning {0:s}.".format(self.return_type.get_string())

    def _prototype(self, out):
        values_dict = {
            "class_name": self.class_name,
            "method": self.name}

        out.write(
            "static PyObject *py{class_name:s}_{method:s}(py{class_name:s} *self)".format(
                **values_dict))

    def PyMethodDef(self, out):
        # This method should not go in the method table as its linked
        # in directly.
        pass


class SelfIteratorMethod(IteratorMethod):
    def write_definition(self, out):
        out.write(
            "\n"
            "/********************************************************\n"
            " * Autogenerated wrapper for function:\n")
        out.write(self.comment())
        out.write(
            "********************************************************/\n")

        self._prototype(out)

        values_dict = {
            "class_name": self.class_name,
            "method": self.name}

        out.write((
            "{{\n"
            "    (({class_name:s}) self->base)->{method:s}(({class_name:s}) self->base);\n"
            "    return PyObject_SelfIter((PyObject *) self);\n"
            "}}\n").format(**values_dict))


class ConstructorMethod(Method):
    # Python constructors are a bit different than regular methods

    def _prototype(self, out):
        values_dict = {
            "class_name": self.class_name,
            "method": self.name}

        out.write(
            "static int py{class_name:s}_init(py{class_name:s} *self, PyObject *args, PyObject *kwds)\n".format(
                **values_dict))

    def prototype(self, out):
        self._prototype(out)

        values_dict = {
            "class_name": self.class_name}

        out.write((
            ";\n"
            "static void py{class_name:s}_initialize_proxies(py{class_name:s} *self, void *item);\n").format(
                **values_dict))

    def write_destructor(self, out):
        values_dict = {
            "class_name": self.class_name,
            "free": FREE}

        out.write((
            "static void {class_name:s}_dealloc(py{class_name:s} *self) {{\n"
            "    struct _typeobject *ob_type = NULL;\n"
            "\n"
            "    if(self != NULL) {{\n"
            "        if(self->base != NULL) {{\n"
            "            if(self->base_is_python_object != 0) {{\n"
            "                Py_DecRef((PyObject*) self->base);\n"
            "            }} else if(self->base_is_internal != 0) {{\n"
            "                {free:s}(self->base);\n"
            "            }}\n"
            "            self->base = NULL;\n"
            "        }}\n"
            "        if(self->python_object2 != NULL) {{\n"
            "            Py_DecRef(self->python_object2);\n"
            "            self->python_object2 = NULL;\n"
            "        }}\n"
            "        if(self->python_object1 != NULL) {{\n"
            "            Py_DecRef(self->python_object1);\n"
            "            self->python_object1 = NULL;\n"
            "        }}\n"
            "        ob_type = Py_TYPE(self);\n"
            "        if(ob_type != NULL && ob_type->tp_free != NULL) {{\n"
            "            ob_type->tp_free((PyObject*) self);\n"
            "        }}\n"
            "    }}\n"
            "}}\n"
            "\n").format(**values_dict))

    def error_condition(self):
        return "    return -1;";

    def initialise_proxies(self, out):
        self.myclass.module.function_definitions.add(
            "py{0:s}_initialize_proxies".format(self.class_name))

        values_dict = {
            "class_name": self.class_name}

        out.write((
            "static void py{class_name:s}_initialize_proxies(py{class_name:s} *self, void *item) {{\n"
            "    {class_name:s} target = ({class_name:s}) item;\n"
            "\n"
            "    /* Maintain a reference to the Python object\n"
            "     * in the C object extension\n"
            "     */\n"
            "    ((Object) item)->extension = self;\n"
            "\n").format(**values_dict))

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
                    "proxied_name": method.proxied.get_name()}

                out.write((
                    "    if(check_method_override((PyObject *) self, &{class_name:s}_Type, \"{name:s}\")) {{\n"
                    "        // Proxy the {name:s} method\n"
                    "        (({definition_class_name:s}) target)->{name:s} = {proxied_name:s};\n"
                    "    }}\n").format(**values_dict))

        out.write("}\n\n")

    def write_definition(self, out):
        self.initialise_proxies(out)
        self._prototype(out)
        values_dict = {
            "class_name": self.class_name,
            "definition_class_name": self.definition_class_name}

        out.write((
            "{{\n"
            "    {class_name:s} result_constructor = NULL;\n").format(
                **values_dict))

        # pdb.set_trace()
        self.write_local_vars(out)

        # Assign the initialise_proxies handler
        out.write((
            "    self->python_object1 = NULL;\n"
            "    self->python_object2 = NULL;\n"
            "\n"
            "    /* Initialise is used to keep a reference on the object?\n"
            "     * If not called no longer valid warnings have been seen\n"
            "     * on Windows.\n"
            "     */\n"
            "    self->initialise = (void *) py{class_name:s}_initialize_proxies;\n"
            "\n").format(**values_dict))

        # Precall preparations
        python_object_index = 1
        for type in self.args:
            out.write(type.pre_call(
                self, python_object_index=python_object_index))
            python_object_index += 1

        # Now call the wrapped function
        out.write((
            "    ClearError();\n"
            "\n"
            "    /* Allocate a new instance */\n"
            "    self->base = ({class_name:s}) alloc_{class_name:s}();\n"
            "    self->base_is_python_object = 0;\n"
            "    self->base_is_internal = 1;\n"
            "    self->object_is_proxied = 0;\n"
            "\n"
            "    /* Update the target by replacing its methods with proxies\n"
            "     * to call back into Python\n"
            "     */\n"
            "    py{class_name:s}_initialize_proxies(self, self->base);\n"
            "\n"
            "    /* Now call the constructor */\n"
            "    Py_BEGIN_ALLOW_THREADS\n"
            "    result_constructor = CONSTRUCT_INITIALIZE({class_name:s}, {definition_class_name:s}, Con, self->base").format(
                **values_dict))

        tmp = ""
        for type in self.args:
            tmp += ", " + type.call_arg()

        self.error_set = True
        out.write(tmp)

        out.write((
            ");\n"
            "    Py_END_ALLOW_THREADS\n"
            "\n"
            "    if(!CheckError(EZero)) {{\n"
            "        char *buffer = NULL;\n"
            "        PyObject *exception = resolve_exception(&buffer);\n"
            "\n"
            "        PyErr_Format(exception, \"%s\", buffer);\n"
            "        ClearError();\n"
            "        goto on_error;\n"
            "    }}\n"
            "    if(result_constructor == NULL) {{\n"
            "        PyErr_Format(PyExc_IOError, \"Unable to construct class {class_name:s}\");\n"
            "        goto on_error;\n"
            "    }}\n"
            "\n"
            "    return 0;\n").format(**values_dict))

        # Write the error part of the function.
        if self.error_set:
            out.write((
                "\n"
                "on_error:\n"
                "    if(self->python_object2 != NULL) {{\n"
                "        Py_DecRef(self->python_object2);\n"
                "        self->python_object2 = NULL;\n"
                "    }}\n"
                "    if(self->python_object1 != NULL) {{\n"
                "        Py_DecRef(self->python_object1);\n"
                "        self->python_object1 = NULL;\n"
                "    }}\n"
                "    if(self->base != NULL) {{\n"
                "        talloc_free(self->base);\n"
                "        self->base = NULL;\n"
                "    }}\n"
                "{0:s}\n").format(self.error_condition()))

        out.write("}\n\n")


class GetattrMethod(Method):
    def __init__(self, class_name, base_class_name, myclass):
        # Cannot use super here due to certain logic in Method.__init__().
        self._attributes = []
        self.base_class_name = base_class_name
        self.class_name = class_name
        self.error_set = True
        self.myclass = myclass
        self.name = ""
        self.return_type = Void("")

        self.rename_class_name(class_name)

    def get_string(self):
        """Retrieves a string representation."""
        result = ""
        for class_name, attr in self.get_attributes():
            result += "    {0:s}\n".format(attr.get_string())

        return result

    def add_attribute(self, attr):
        if attr.name:
            self._attributes.append([self.class_name, attr])

    def rename_class_name(self, new_name):
        """This allows us to rename the class_name at a later stage.
        Required for late initialization of Structs whose name is not
        know until much later on.
        """
        # TODO fix this behavior, new_name can be None but it is unclear what
        # the behavious should be. Python 3 requires the values to be set to
        # string types.
        if not new_name:
            self.class_name = ""
            self.name = ""
        else:
            self.class_name = new_name
            self.name = "py{0:s}_getattr".format(new_name)

        for attribure in self._attributes:
            attribure[0] = new_name

    def get_attributes(self):
        for class_name, attr in self._attributes:
            try:
                # If its not an active struct, skip it
                if (not type_dispatcher[attr.type].active and
                    not attr.type in self.myclass.module.active_structs):
                    continue

            except KeyError:
                pass

            yield class_name, attr

    def clone(self, class_name):
        result = self.__class__(class_name, self.base_class_name, self.myclass)
        result._attributes = self._attributes[:]

        return result

    def prototype(self, out):
        if not self.name:
            return

        values_dict = {
            "class_name": self.class_name,
            "name": self.name}

        # Define getattr.
        out.write(
            "static PyObject *{name:s}(py{class_name:s} *self, PyObject *name);\n".format(
                **values_dict))

        # Define getters.
        for _, attr in self.get_attributes():
            values_dict = {
                "class_name": self.class_name,
                "name": attr.name}

            out.write(
                "PyObject *py{class_name:s}_{name:s}_getter(py{class_name:s} *self, PyObject *arguments);\n".format(
                    **values_dict))

    def built_ins(self, out):
        """Check for some built in attributes we need to support."""
        out.write(
            "    if(strcmp(name, \"__members__\") == 0) {\n"
            "        PyMethodDef *i = NULL;\n"
            "        PyObject *list_object = NULL;\n"
            "        PyObject *string_object = NULL;\n"
            "\n"
            "        list_object = PyList_New(0);\n"
            "        if(list_object == NULL) {\n"
            "            goto on_error;\n"
            "        }\n"
            "\n")

        # Add attributes
        for class_name, attr in self.get_attributes():
            values_dict = {
                "name": attr.name}

            out.write((
                "#if PY_MAJOR_VERSION >= 3\n"
                "        string_object = PyUnicode_FromString(\"{name:s}\");\n"
                "#else\n"
                "        string_object = PyString_FromString(\"{name:s}\");\n"
                "#endif\n"
                "        PyList_Append(list_object, string_object);\n"
                "        Py_DecRef(string_object);\n"
                "\n").format(**values_dict))

        # Add methods
        out.write((
            "\n"
            "        for(i = {0:s}_methods; i->ml_name; i++) {{\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "            string_object = PyUnicode_FromString(i->ml_name);\n"
            "#else\n"
            "            string_object = PyString_FromString(i->ml_name);\n"
            "#endif\n"
            "            PyList_Append(list_object, string_object);\n"
            "            Py_DecRef(string_object);\n"
            "        }}\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        if( utf8_string_object != NULL ) {{\n"
            "            Py_DecRef(utf8_string_object);\n"
            "        }}\n"
            "#endif\n"
            "        return list_object;\n"
            "    }}\n").format(self.class_name))

    def write_definition(self, out):
        if not self.name:
            return

        values_dict = {
            "class_name": self.class_name,
            "name": self.name}

        out.write((
            "static PyObject *py{class_name:s}_getattr(py{class_name:s} *self, PyObject *pyname) {{\n"
            "    PyObject *result = NULL;\n"
            "    char *name = NULL;\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    PyObject *utf8_string_object  = NULL;\n"
            "#endif\n"
            "\n"
            "    // Try to hand it off to the Python native handler first\n"
            "    result = PyObject_GenericGetAttr((PyObject*) self, pyname);\n"
            "\n"
            "    if(result) {{\n"
            "        return result;\n"
            "    }}\n"
            "\n"
            "    PyErr_Clear();\n"
            "    // No - nothing interesting was found by python\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    utf8_string_object = PyUnicode_AsUTF8String(pyname);\n"
            "\n"
            "    if(utf8_string_object != NULL) {{\n"
            "        name = PyBytes_AsString(utf8_string_object);\n"
            "    }}\n"
            "#else\n"
            "    name = PyString_AsString(pyname);\n"
            "#endif\n"
            "\n"
            "    if(!self->base) {{\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "        if( utf8_string_object != NULL ) {{\n"
            "            Py_DecRef(utf8_string_object);\n"
            "        }}\n"
            "#endif\n"
            "        return PyErr_Format(PyExc_RuntimeError, \"Wrapped object ({class_name:s}.{name:s}) no longer valid\");\n"
            "    }}\n"
            "    if(!name) {{\n"
            "        goto on_error;\n"
            "    }}\n").format(**values_dict))

        self.built_ins(out)

        out.write(
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    if( utf8_string_object != NULL ) {{\n"
            "        Py_DecRef(utf8_string_object);\n"
            "    }}\n"
            "#endif\n"
            "    return PyObject_GenericGetAttr((PyObject *) self, pyname);\n")

        # Write the error part of the function.
        if self.error_set:
            out.write(
                "on_error:\n"
                "#if PY_MAJOR_VERSION >= 3\n"
                "    if( utf8_string_object != NULL ) {{\n"
                "        Py_DecRef(utf8_string_object);\n"
                "    }}\n"
                "#endif\n" + self.error_condition())

        out.write("}\n\n")

        self.write_definition_getters(out)

    def write_definition_getters(self, out):
        for _, attr in self.get_attributes():
            if self.base_class_name:
                call = "((({0:s}) self->base)->{1:s})".format(
                    self.class_name, attr.name)
            else:
                call = "(self->base->{0:s})".format(attr.name)

            values_dict = {
                "class_name": self.class_name,
                "name": attr.name,
                "python_obj": attr.to_python_object(),
                "python_assign": attr.assign(call, self, borrowed=True),
                "python_def": attr.definition(sense="out")}

            out.write((
                "PyObject *py{class_name:s}_{name:s}_getter(py{class_name:s} *self, PyObject *arguments) {{\n"
                "    PyObject *Py_result = NULL;\n"
                "{python_def:s}\n"
                "\n"
                "{python_assign:s}\n"
                "{python_obj:s}\n"
                "\n"
                "    return Py_result;\n"
                "\n").format(**values_dict))

            # Work-around for the String class that generates code that contains "goto on_error".
            if isinstance(attr, String):
                out.write((
                    "on_error:\n"
                    "    {0:s}\n").format(attr.error_value))

            out.write("}\n\n")

    def PyGetSetDef(self, out):
        for _, attr in self.get_attributes():
            # TODO: improve docstring.
            docstring = "{0:s}.".format(attr.name)
            values_dict = {
                "class_name": self.class_name,
                "docstring": format_as_docstring(docstring),
                "name": attr.name}

            out.write((
                "    {{ \"{name:s}\",\n"
                "      (getter) py{class_name:s}_{name:s}_getter,\n"
                "      (setter) 0,\n"
                "      \"{docstring:s}\",\n"
                "      NULL }},\n"
                "\n").format(**values_dict))


class ProxiedMethod(Method):
    def __init__(self, method, myclass):
        # Cannot use super here due to certain logic in Method.__init__().
        self.args = method.args
        self.base_class_name = method.base_class_name
        self.class_name = method.class_name
        self.defaults = {}
        self.definition_class_name = method.definition_class_name
        self.docstring = "Proxy for {0:s}".format(method.name)
        self.error_set = False
        self.exception = None
        self.method = method
        self.myclass = myclass
        self.name = method.name
        self.return_type = method.return_type

    def get_name(self):
        return "Proxied{0:s}_{1:s}".format(
            self.myclass.class_name, self.name)

    def _prototype(self, out):
        out.write("static {0:s} {1:s}({2:s} self".format(
            self.return_type.type.strip(), self.get_name(),
            self.definition_class_name))

        for arg in self.args:
            tmp = arg.comment().strip()
            if tmp:
                out.write(", {0:s}".format(tmp))

        out.write(")")

    def prototype(self, out):
        self._prototype(out)
        out.write(";\n")

    def write_definition(self, out):
        name = self.get_name()
        if name in self.myclass.module.function_definitions:
            return
        else:
            self.myclass.module.function_definitions.add(name)

        self._prototype(out)
        self._write_definition(out)

    def _write_definition(self, out):
        out.write(
            " {\n"
            "    PyGILState_STATE gil_state;\n"
            "    PyObject *Py_result = NULL;\n"
            "    PyObject *method_name = NULL;\n")

        out.write(self.return_type.returned_python_definition())

        for arg in self.args:
            out.write(arg.local_definition())
            out.write("PyObject *py_{0:s} = NULL;\n".format(arg.name))

        out.write((
            "\n"
            "    // Grab the GIL so we can do Python stuff\n"
            "    gil_state = PyGILState_Ensure();\n"
            "\n"
            "#if PY_MAJOR_VERSION >= 3\n"
            "    method_name = PyUnicode_FromString(\"{0:s}\");\n"
            "#else\n"
            "    method_name = PyString_FromString(\"{0:s}\");\n"
            "#endif\n").format(self.name))

        out.write("\n// Obtain Python objects for all the args:\n")
        for arg in self.args:
            out.write(arg.to_python_object(
                result=("py_{0:s}".format(arg.name)), sense="proxied",
                BORROWED=True))

        out.write((
            "    if(((Object) self)->extension == NULL) {{\n"
            "        RaiseError(ERuntimeError, \"No proxied object in {0:s}\");\n"
            "        goto on_error;\n"
            "    }}\n").format(self.myclass.class_name))

        out.write(
            "\n"
            "    // Now call the method\n"
            "    PyErr_Clear();\n"
            "    Py_result = PyObject_CallMethodObjArgs(((Object) self)->extension, method_name, ")

        for arg in self.args:
            out.write("py_{0:s},".format(arg.name))

        # Sentinal
        out.write(
            "NULL);\n"
            "\n")

        self.error_set = True
        out.write((
            "    /* Check for Python errors */\n"
            "    if(PyErr_Occurred()) {{\n"
            "        pytsk_fetch_error();\n"
            "\n"
            "        goto on_error;\n"
            "    }}\n"
            "\n").format(CURRENT_ERROR_FUNCTION))

        for arg in self.args:
            out.write(arg.python_proxy_post_call())

        # Now convert the Python value back to a value
        out.write(self.return_type.from_python_object(
            "Py_result", self.return_type.name, self, context="self"))

        out.write(
            "    if(Py_result != NULL) {\n"
            "        Py_DecRef(Py_result);\n"
            "    }\n"
            "    Py_DecRef(method_name);\n"
            "\n")

        # Decref all our Python objects:
        for arg in self.args:
            out.write((
                "    if(py_{0:s} != NULL) {{\n"
                "        Py_DecRef(py_{0:s});\n"
                "    }}\n").format(arg.name))

        out.write((
            "    PyGILState_Release(gil_state);\n"
            "\n"
            "    {0:s}\n").format(
                self.return_type.return_value("func_return")))

        if self.error_set:
            out.write(
                "\n"
                "on_error:\n"
                "    if(Py_result != NULL) {\n"
                "        Py_DecRef(Py_result);\n"
                "    }\n"
                "    Py_DecRef(method_name);\n"
                "\n")

            # Decref all our Python objects:
            for arg in self.args:
                out.write((
                    "    if(py_{0:s} != NULL) {{\n"
                    "        Py_DecRef(py_{0:s});\n"
                    "    }}\n").format(arg.name))

            out.write((
                "    PyGILState_Release(gil_state);\n"
                "\n"
                "    {0:s}\n").format(
                    self.error_condition()))

        out.write(
            "}\n"
            "\n")

    def error_condition(self):
        values_dict = {
            "result": "func_return"}
        return self.return_type.error_value.format(**values_dict)


class StructConstructor(ConstructorMethod):
    """ A constructor for struct wrappers - basically just allocate
    memory for the struct.
    """

    def prototype(self, out):
        return Method.prototype(self, out)

    def write_destructor(self, out):
        """We do not deallocate memory from structs.

        This is a real problem since struct memory is usually
        allocated in some proprietary way and we cant just call free
        on it when done.
        """
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "static void {class_name:s}_dealloc(py{class_name:s} *self) {{\n"
            "    struct _typeobject *ob_type = NULL;\n"
            "\n"
            "    if(self != NULL) {{\n"
            "        if(self->base != NULL) {{\n"
            "            self->base = NULL;\n"
            "        }}\n"
            "        ob_type = Py_TYPE(self);\n"
            "        if(ob_type != NULL && ob_type->tp_free != NULL) {{\n"
            "            ob_type->tp_free((PyObject*) self);\n"
            "        }}\n"
            "    }}\n"
            "}}\n"
            "\n").format(**values_dict))

    def write_definition(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "static int py{class_name:s}_init(py{class_name:s} *self, PyObject *args, PyObject *kwds) {{\n"
            "    // Base is borrowed from another object.\n"
            "    self->base = NULL;\n"
            "    return 0;\n"
            "}}\n"
            "\n").format(**values_dict))


class EmptyConstructor(ConstructorMethod):
    def prototype(self, out):
        return Method.prototype(self, out)

    def write_definition(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write(
            "static int py{class_name:s}_init(py{class_name:s} *self, PyObject *args, PyObject *kwds) {{\n"
            "    return 0;\n"
            "}}\n"
            "\n".format(**values_dict))


class ClassGenerator(object):
    docstring = ""

    def __init__(self, class_name, base_class_name, module):
        self.class_name = class_name
        self.methods = []
        # self.methods = [DefinitionMethod(
        #     class_name, base_class_name, "_definition", [], "",
        #     myclass=self)]
        self.module = module
        self.constructor = EmptyConstructor(
            class_name, base_class_name, "Con", [], "", myclass=self)

        self.base_class_name = base_class_name
        self.attributes = GetattrMethod(
            self.class_name, self.base_class_name, self)
        self.modifier = set()
        self.active = True
        self.iterator = None

    def get_string(self):
        """Retrieves a string representation."""
        result = (
            "#{0:s}\n"
            "Class {1:s}({2:s}):\n"
            "    Constructor:{3:s}\n"
            "    Attributes:\n{4:s}\n"
            "    Methods:\n").format(
                self.docstring, self.class_name, self.base_class_name,
                self.constructor.get_string(), self.attributes.get_string())

        for method in self.methods:
            result += "        {0:s}\n".format(method.get_string())

        return result

    def prepare(self):
        """ This method is called just before we need to write the
        output and allows us to do any last minute fixups.
        """
        pass

    def is_active(self):
        """Returns true if this class is active and should be generated"""
        if self.class_name in self.module.active_structs:
            return True

        if (not self.active or self.modifier and
            ("PRIVATE" in self.modifier or "ABSTRACT" in self.modifier)):
            log("{0:s} is not active {1!s}".format(
                self.class_name, self.modifier))
            return False

        return True

    def clone(self, new_class_name):
        """Creates a clone of this class - usefull when implementing
        class extensions.
        """
        result = ClassGenerator(new_class_name, self.class_name, self.module)
        result.constructor = self.constructor.clone(new_class_name)
        result.methods = [
            method.clone(new_class_name) for method in self.methods]
        result.attributes = self.attributes.clone(new_class_name)

        return result

    def add_attribute(self, attr_name, attr_type, modifier, *args, **kwargs):
        try:
            if not self.module.classes[attr_type].is_active():
                return
        except KeyError:
            pass

        try:
            # All attribute references are always borrowed - that
            # means we dont want to free them after accessing them
            type_class = dispatch(
                attr_name, "BORROWED {0:s}".format(attr_type), *args, **kwargs)
        except KeyError:
            # TODO: fix that self.class_name is None.
            log("Unknown attribute type {0:s} for {1!s}.{2:s}".format(
                attr_type, self.class_name, attr_name))
            return

        type_class.attributes.add(modifier)
        self.attributes.add_attribute(type_class)

    def add_constructor(self, method_name, args, return_type, docstring):
        if method_name.startswith("Con"):
            self.constructor = ConstructorMethod(
                self.class_name, self.base_class_name, method_name, args,
                return_type, myclass=self)
            self.constructor.docstring = docstring

    def struct(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "\n"
            "typedef struct {{\n"
            "    PyObject_HEAD\n"
            "    {class_name:s} base;\n"
            "    int base_is_python_object;\n"
            "    int base_is_internal;\n"
            "    PyObject *python_object1;\n"
            "    PyObject *python_object2;\n"
            "    int object_is_proxied;\n"
            "\n"
            "    void (*initialise)(Gen_wrapper self, void *item);\n"
            "}} py{class_name:s};\n").format(**values_dict))

    def code(self, out):
        if not self.constructor:
            raise RuntimeError(
                "No constructor found for class {0:s}".format(self.class_name))

        self.constructor.write_destructor(out)
        self.constructor.write_definition(out)
        if self.attributes:
            self.attributes.write_definition(out)

        for method in self.methods:
            method.write_definition(out)

            if hasattr(method, "proxied"):
                method.proxied.write_definition(out)

    def initialise(self):
        values_dict = {
            "class_name": self.class_name}

        result = (
            "python_wrappers[TOTAL_CLASSES].class_ref = (Object)&__{class_name:s};\n"
            "python_wrappers[TOTAL_CLASSES].python_type = &{class_name:s}_Type;\n").format(**values_dict)

        func_name = "py{class_name:s}_initialize_proxies".format(**values_dict)
        if func_name in self.module.function_definitions:
            result += (
                "python_wrappers[TOTAL_CLASSES].initialize_proxies = (void (*)(Gen_wrapper, void *)) &{0:s};\n").format(
                func_name)

        result += "TOTAL_CLASSES++;\n"
        return result

    def PyGetSetDef(self, out):
        out.write(
            "static PyGetSetDef {0:s}_get_set_definitions[] = {{\n".format(
                self.class_name))

        if self.attributes:
            self.attributes.PyGetSetDef(out)

        out.write(
            "    {NULL, NULL, NULL, NULL, NULL}  /* Sentinel */\n"
            "};\n"
            "\n")

    def PyMethodDef(self, out):
        out.write("static PyMethodDef {0:s}_methods[] = {{\n".format(
            self.class_name))

        for method in self.methods:
            method.PyMethodDef(out)

        out.write(
            "    {NULL, NULL, 0, NULL}  /* Sentinel */\n"
            "};\n"
            "\n")

    def prototypes(self, out):
        """Write prototype suitable for .h file"""
        out.write("static PyTypeObject {0:s}_Type;\n".format(self.class_name))
        self.constructor.prototype(out)

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

    def numeric_protocol_int(self):
        pass

    def numeric_protocol_nonzero(self):
        values_dict = {
            "class_name": self.class_name}

        return (
            "static int {class_name:s}_nonzero(py{class_name:s} *v) {{\n"
            "    return v->base != 0;\n"
            "}}\n").format(**values_dict)

    def numeric_protocol(self, out):
        args = {
            "class": self.class_name}
        for type, func in [
            ("nonzero", self.numeric_protocol_nonzero),
            ("int", self.numeric_protocol_int)]:

            definition = func()
            if definition:
                out.write(definition)
                args[type] = "{0:s}_{1:s}".format(self.class_name, type)
            else:
                args[type] = "0"

        out.write((
            "#if PY_MAJOR_VERSION >= 3\n"
            "static PyNumberMethods {class:s}_as_number = {{\n"
            "    (binaryfunc)    0,             /* nb_add */\n"
            "    (binaryfunc)    0,             /* nb_subtract */\n"
            "    (binaryfunc)    0,             /* nb_multiply */\n"
            "    (binaryfunc)    0,             /* nb_remainder */\n"
            "    (binaryfunc)    0,             /* nb_divmod */\n"
            "    (ternaryfunc)   0,             /* nb_power */\n"
            "    (unaryfunc)     0,             /* nb_negative */\n"
            "    (unaryfunc)     0,             /* nb_positive */\n"
            "    (unaryfunc)     0,             /* nb_absolute */\n"
            "    (inquiry)       {nonzero:s},   /* nb_bool */\n"
            "    (unaryfunc)     0,             /* nb_invert */\n"
            "    (binaryfunc)    0,             /* nb_lshift */\n"
            "    (binaryfunc)    0,             /* nb_rshift */\n"
            "    (binaryfunc)    0,             /* nb_and */\n"
            "    (binaryfunc)    0,             /* nb_xor */\n"
            "    (binaryfunc)    0,             /* nb_or */\n"
            "    (unaryfunc)     {int:s},       /* nb_int */\n"
            "    (void *)        NULL,          /* nb_reserved */\n"
            "    (unaryfunc)     0,             /* nb_float */\n"
            "\n"
            "    (binaryfunc)    0,             /* nb_inplace_add */\n"
            "    (binaryfunc)    0,             /* nb_inplace_subtract */\n"
            "    (binaryfunc)    0,             /* nb_inplace_multiply */\n"
            "    (binaryfunc)    0,             /* nb_inplace_remainder */\n"
            "    (ternaryfunc)   0,             /* nb_inplace_power */\n"
            "    (binaryfunc)    0,             /* nb_inplace_lshift */\n"
            "    (binaryfunc)    0,             /* nb_inplace_rshift */\n"
            "    (binaryfunc)    0,             /* nb_inplace_and */\n"
            "    (binaryfunc)    0,             /* nb_inplace_xor */\n"
            "    (binaryfunc)    0,             /* nb_inplace_or */\n"
            "\n"
            "    (binaryfunc)    0,             /* nb_floor_divide */\n"
            "    (binaryfunc)    0,             /* nb_true_divide */\n"
            "    (binaryfunc)    0,             /* nb_inplace_floor_divide */\n"
            "    (binaryfunc)    0,             /* nb_inplace_true_divide */\n"
            "\n"
            "    (unaryfunc)     0,             /* nb_index */\n"
            "}};\n"
            "#else\n"
            "static PyNumberMethods {class:s}_as_number = {{\n"
            "    (binaryfunc)    0,             /* nb_add */\n"
            "    (binaryfunc)    0,             /* nb_subtract */\n"
            "    (binaryfunc)    0,             /* nb_multiply */\n"
            "    (binaryfunc)    0,             /* nb_divide */\n"
            "    (binaryfunc)    0,             /* nb_remainder */\n"
            "    (binaryfunc)    0,             /* nb_divmod */\n"
            "    (ternaryfunc)   0,             /* nb_power */\n"
            "    (unaryfunc)     0,             /* nb_negative */\n"
            "    (unaryfunc)     0,             /* nb_positive */\n"
            "    (unaryfunc)     0,             /* nb_absolute */\n"
            "    (inquiry)       {nonzero:s},   /* nb_nonzero */\n"
            "    (unaryfunc)     0,             /* nb_invert */\n"
            "    (binaryfunc)    0,             /* nb_lshift */\n"
            "    (binaryfunc)    0,             /* nb_rshift */\n"
            "    (binaryfunc)    0,             /* nb_and */\n"
            "    (binaryfunc)    0,             /* nb_xor */\n"
            "    (binaryfunc)    0,             /* nb_or */\n"
            "    (coercion)      0,             /* nb_coerce */\n"
            "    (unaryfunc)     {int:s},       /* nb_int */\n"
            "    (unaryfunc)     0,             /* nb_long */\n"
            "    (unaryfunc)     0,             /* nb_float */\n"
            "    (unaryfunc)     0,             /* nb_oct */\n"
            "    (unaryfunc)     0,             /* nb_hex */\n"
            "\n"
            "    (binaryfunc)    0,             /* nb_inplace_add */\n"
            "    (binaryfunc)    0,             /* nb_inplace_subtract */\n"
            "    (binaryfunc)    0,             /* nb_inplace_multiply */\n"
            "    (binaryfunc)    0,             /* nb_inplace_divide */\n"
            "    (binaryfunc)    0,             /* nb_inplace_remainder */\n"
            "    (ternaryfunc)   0,             /* nb_inplace_power */\n"
            "    (binaryfunc)    0,             /* nb_inplace_lshift */\n"
            "    (binaryfunc)    0,             /* nb_inplace_rshift */\n"
            "    (binaryfunc)    0,             /* nb_inplace_and */\n"
            "    (binaryfunc)    0,             /* nb_inplace_xor */\n"
            "    (binaryfunc)    0,             /* nb_inplace_or */\n"
            "\n"
            "    (binaryfunc)    0,             /* nb_floor_divide */\n"
            "    (binaryfunc)    0,             /* nb_true_divide */\n"
            "    (binaryfunc)    0,             /* nb_inplace_floor_divide */\n"
            "    (binaryfunc)    0,             /* nb_inplace_true_divide */\n"
            "\n"
            "    (unaryfunc)     0,             /* nb_index */\n"
            "}};\n"
            "#endif /* PY_MAJOR_VERSION >= 3 */\n"
            "\n").format(**args))

        return "&{class:s}_as_number".format(**args)

    def PyTypeObject(self, out):
        docstring = "{0:s}: {1:s}".format(
            self.class_name, format_as_docstring(self.docstring))

        args = {
            "class": self.class_name,
            "module": self.module.name,
            "iterator": 0,
            "iternext": 0,
            "tp_str": 0,
            "tp_eq": 0,
            "getattr_func": 0,
            "docstring": docstring}

        if self.attributes:
            args["getattr_func"] = self.attributes.name

        args["numeric_protocol"] = self.numeric_protocol(out)
        if "ITERATOR" in self.modifier:
            args["iterator"] = "PyObject_SelfIter"
            args["iternext"] = "py{0:s}_iternext".format(self.class_name)

        if "SELF_ITER" in self.modifier:
            args["iterator"] = "py{0:s}___iter__".format(self.class_name)

        if "TP_STR" in self.modifier:
            args["tp_str"] = "py{0:s}___str__".format(self.class_name)

        if "TP_EQUAL" in self.modifier:
            args["tp_eq"] = "{0:s}_eq".format(self.class_name)

        out.write((
            "static PyTypeObject {class:s}_Type = {{\n"
            "    PyVarObject_HEAD_INIT(NULL, 0)\n"
            "    /* tp_name */\n"
            "    \"{module:s}.{class:s}\",\n"
            "    /* tp_basicsize */\n"
            "    sizeof(py{class:s}),\n"
            "    /* tp_itemsize */\n"
            "    0,\n"
            "    /* tp_dealloc */\n"
            "    (destructor) {class:s}_dealloc,\n"
            "    /* tp_print */\n"
            "    0,\n"
            "    /* tp_getattr */\n"
            "    0,\n"
            "    /* tp_setattr */\n"
            "    0,\n"
            "    /* tp_compare */\n"
            "    0,\n"
            "    /* tp_repr */\n"
            "    0,\n"
            "    /* tp_as_number */\n"
            "    {numeric_protocol:s},\n"
            "    /* tp_as_sequence */\n"
            "    0,\n"
            "    /* tp_as_mapping */\n"
            "    0,\n"
            "    /* tp_hash */\n"
            "    0,\n"
            "    /* tp_call */\n"
            "    0,\n"
            "    /* tp_str */\n"
            "    (reprfunc) {tp_str!s},\n"
            "    /* tp_getattro */\n"
            "    (getattrofunc) {getattr_func!s},\n"
            "    /* tp_setattro */\n"
            "    0,\n"
            "    /* tp_as_buffer */\n"
            "    0,\n"
            "    /* tp_flags */\n"
            "    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,\n"
            "    /* tp_doc */\n"
            "    \"{docstring:s}\",\n"
            "    /* tp_traverse */\n"
            "    0,\n"
            "    /* tp_clear */\n"
            "    0,\n"
            "    /* tp_richcompare */\n"
            "    {tp_eq!s},\n"
            "    /* tp_weaklistoffset */\n"
            "    0,\n"
            "    /* tp_iter */\n"
            "    (getiterfunc) {iterator!s},\n"
            "    /* tp_iternext */\n"
            "    (iternextfunc) {iternext!s},\n"
            "    /* tp_methods */\n"
            "    {class:s}_methods,\n"
            "    /* tp_members */\n"
            "    0,\n"
            "    /* tp_getset */\n"
            "    {class:s}_get_set_definitions,\n"
            "    /* tp_base */\n"
            "    0,\n"
            "    /* tp_dict */\n"
            "    0,\n"
            "    /* tp_descr_get */\n"
            "    0,\n"
            "    /* tp_descr_set */\n"
            "    0,\n"
            "    /* tp_dictoffset */\n"
            "    0,\n"
            "    /* tp_init */\n"
            "    (initproc) py{class:s}_init,\n"
            "    /* tp_alloc */\n"
            "    0,\n"
            "    /* tp_new */\n"
            "    0,\n"
            "}};\n"
            "\n").format(**args))


class StructGenerator(ClassGenerator):
    """A wrapper generator for structs."""

    def __init__(self, class_name, module):
        self.class_name = class_name
        self.methods = []
        self.module = module
        self.base_class_name = None
        self.active = False
        self.modifier = set()
        self.constructor = None
        self.attributes = GetattrMethod(
            self.class_name, self.base_class_name, self)

    def get_string(self):
        """Retrieves a string representation."""
        return (
            "# {0:s}\n"
            "Struct {1:s}:\n"
            "{2:s}\n").format(
                self.docstring, self.class_name, self.attributes.get_string())

    def prepare(self):
        # This is needed for late stage initialization - sometimes
        # our class_name is not know until now.
        if not self.constructor:
            self.constructor = StructConstructor(
                self.class_name, self.base_class_name, "Con", [], "void",
                myclass=self)

            self.attributes.rename_class_name(self.class_name)
            for x in self.attributes._attributes:
                x[1].attributes.add("FOREIGN")

    def struct(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "\n"
            "typedef struct {{\n"
            "    PyObject_HEAD\n"
            "    {class_name:s} *base;\n"
            "    int base_is_python_object;\n"
            "    int base_is_internal;\n"
            "    PyObject *python_object1;\n"
            "    PyObject *python_object2;\n"
            "    int object_is_proxied;\n"
            "    {class_name:s} *cbase;\n"
            "}} py{class_name:s};\n").format(
                **values_dict))

    def initialise(self):
        return ""


class EnumConstructor(ConstructorMethod):
    def prototype(self, out):
        return Method.prototype(self, out)

    def write_destructor(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "static void {class_name:s}_dealloc(py{class_name:s} *self) {{\n"
            "    struct _typeobject *ob_type = NULL;\n"
            "\n"
            "    if(self != NULL) {{\n"
            "        Py_DecRef(self->value);\n"
            "        ob_type = Py_TYPE(self);\n"
            "        if(ob_type != NULL && ob_type->tp_free != NULL) {{\n"
            "            ob_type->tp_free((PyObject*) self);\n"
            "        }}\n"
            "    }}\n"
            "}}\n").format(**values_dict))

    def write_definition(self, out):
        self.myclass.modifier.add("TP_STR")
        self.myclass.modifier.add("TP_EQUAL")
        self._prototype(out)

        values_dict = {
            "class_name": self.class_name}

        out.write((
            "{{\n"
            "    static char *kwlist[] = {{\"value\", NULL}};\n"
            "\n"
            "    if(!PyArg_ParseTupleAndKeywords(args, kwds, \"O\", kwlist, &self->value)) {{\n"
            "        goto on_error;\n"
            "    }}\n"
            "\n"
            "    Py_IncRef(self->value);\n"
            "\n"
            "    return 0;\n"
            "\n"
            "on_error:\n"
            "    return -1;\n"
            "}}\n"
            "\n"
            "static PyObject *py{class_name:s}___str__(py{class_name:s} *self) {{\n"
            "    PyObject *result = PyDict_GetItem({class_name:s}_rev_lookup, self->value);\n"
            "\n"
            "    if(result) {{\n"
            "        Py_IncRef(result);\n"
            "    }} else {{\n"
            "        result = PyObject_Str(self->value);\n"
            "    }}\n"
            "\n"
            "    return result;\n"
            "}}\n"
            "\n"
            "static PyObject * {class_name:s}_eq(PyObject *me, PyObject *other, int op) {{\n"
            "    py{class_name:s} *self = (py{class_name:s} *)me;\n"
            "    int other_int = PyLong_AsLong(other);\n"
            "    int my_int = 0;\n"
            "    PyObject *result = Py_False;\n"
            "\n"
            "    if(CheckError(EZero)) {{\n"
            "        my_int = PyLong_AsLong(self->value);\n"
            "        switch(op) {{\n"
            "            case Py_EQ:\n"
            "                result = my_int == other_int? Py_True: Py_False;\n"
            "                break;\n"
            "            case Py_NE:\n"
            "                result = my_int != other_int? Py_True: Py_False;\n"
            "                break;\n"
            "         default:\n"
            "            return Py_NotImplemented;\n"
            "       }}\n"
            "    }} else {{\n"
            "        return NULL;\n"
            "    }}\n"
            "\n"
            "    ClearError();\n"
            "\n"
            "    Py_IncRef(result);\n"
            "    return result;\n"
            "}}\n"
            "\n").format(**values_dict))


class Enum(StructGenerator):
    def __init__(self, name, module):
        super(Enum, self).__init__(name, module)
        self.values = []
        self.name = name
        self.attributes = None
        self.active = True

    def get_string(self):
        """Retrieves a string representation."""
        result = "Enum {0:s}:\n".format(self.name)
        for attr in self.values:
            result += "    {0:s}\n".format(attr)

        return result

    def prepare(self):
        self.constructor = EnumConstructor(
            self.class_name, self.base_class_name, "Con", [], "void",
            myclass=self)
        StructGenerator.prepare(self)

    def struct(self, out):
        values_dict = {
            "class_name": self.class_name}

        out.write((
            "\n"
            "typedef struct {{\n"
            "    PyObject_HEAD\n"
            "    PyObject *value;\n"
            "}} py{class_name:s};\n"
            "\n"
            "PyObject *{class_name:s}_Dict_lookup;\n"
            "PyObject *{class_name:s}_rev_lookup;\n").format(
            **values_dict))

    def PyGetSetDef(self, out):
        out.write((
            "static PyGetSetDef {0:s}_get_set_definitions[] = {{\n"
            "    {{NULL, NULL, NULL, NULL, NULL}}  /* Sentinel */\n"
            "}};\n"
            "\n").format(self.class_name))

    def PyMethodDef(self, out):
        out.write((
            "static PyMethodDef {0:s}_methods[] = {{\n"
            "    {{NULL, NULL, 0, NULL}}  /* Sentinel */\n"
            "}};\n"
            "\n").format(self.class_name))

    def numeric_protocol_nonzero(self):
        pass

    def numeric_protocol_int(self):
        values_dict = {
            "class_name": self.class_name}

        return (
            "static PyObject *{class_name:s}_int(py{class_name:s} *self) {{\n"
            "    Py_IncRef(self->value);\n"
            "    return self->value;\n"
            "}}\n").format(**values_dict)

    def initialise(self):
        values_dict = {
            "class_name": self.class_name}

        result = (
            "{class_name:s}_Dict_lookup = PyDict_New();\n"
            "{class_name:s}_rev_lookup = PyDict_New();\n").format(
            **values_dict)

        if self.values:
            result += (
                "{\n"
                "    PyObject *integer_object = NULL;\n"
                "    PyObject *string_object = NULL;\n")

            for attr in self.values:
                values_dict = {
                    "class_name": self.class_name,
                    "value": attr}

                result += (
                    "    integer_object = PyLong_FromLong({value:s});\n"
                    "\n"
                    "#if PY_MAJOR_VERSION >= 3\n"
                    "    string_object = PyUnicode_FromString(\"{value:s}\");\n"
                    "#else\n"
                    "    string_object = PyString_FromString(\"{value:s}\");\n"
                    "#endif\n"
                    "    PyDict_SetItem({class_name:s}_Dict_lookup, string_object, integer_object);\n"
                    "    PyDict_SetItem({class_name:s}_rev_lookup, integer_object, string_object);\n"
                    "    Py_DecRef(integer_object);\n"
                    "    Py_DecRef(string_object);\n"
                    "\n").format(**values_dict)

            result += "}\n"

        return result


class EnumType(Integer):
    buildstr = "i"

    def __init__(self, name, type, *args, **kwargs):
        super(EnumType, self).__init__(name, type, *args, **kwargs)
        self.type = type

    def definition(self, default=None, **kwargs):
        # Force the enum to be an int just in case the compiler chooses
        # a random size.
        if default:
            return "    int {0:s} = {1:s};\n".format(self.name, default)
        else:
            return "    int UNUSED {0:s} = 0;\n".format(self.name)

    def to_python_object(self, name=None, result="Py_result", **kwargs):
        name = name or self.name
        return (
            "PyErr_Clear();\n"
            "{0:s} = PyObject_CallMethod(g_module, \"{1:s}\", \"K\", (uint64_t){2:s});\n").format(
                result, self.type, name)

    def pre_call(self, method, **kwargs):
        method.error_set = True

        values_dict = {
            "name": self.name,
            "type": self.type}

        return (
            "/* Check if the integer passed is actually a valid member\n"
            " * of the enum. Enum value of 0 is always allowed.\n"
            " */\n"
            "if({name:s}) {{\n"
            "    PyObject *py_{name:s} = NULL;\n"
            "    PyObject *tmp = NULL;\n"
            "\n"
            "    py_{name:s} = PyLong_FromLong({name:s});\n"
            "    tmp = PyDict_GetItem({type:s}_rev_lookup, py_{name:s});\n"
            "\n"
            "    Py_DecRef(py_{name:s});\n"
            "    if(!tmp) {{\n"
            "        PyErr_Format(PyExc_RuntimeError, \"value %lu is not valid for Enum {type:s} of arg '{name:s}'\", (unsigned long){name:s});\n"
            "        goto on_error;\n"
            "    }}\n"
            "}}\n").format(**values_dict)


class HeaderParser(lexer.SelfFeederMixIn):
    tokens = [
        ["INITIAL", r"#define\s+", "PUSH_STATE", "DEFINE"],
        ["DEFINE", r"([A-Za-z_0-9]+)\s+[^\n]+", "DEFINE,POP_STATE", None],
        ["DEFINE", r"\n", "POP_STATE", None],
        # Ignore macros with args
        ["DEFINE", r"\([^\n]+", "POP_STATE", None],

        # Recognize ansi c comments
        [".", r"/\*(.)", "PUSH_STATE", "COMMENT"],
        ["COMMENT", r"(.+?)\*/\s+", "COMMENT_END,POP_STATE", None],
        ["COMMENT", r"(.+)", "COMMENT", None],

        # And c++ comments
        [".", r"//([^\n]+)", "COMMENT", None],

        # An empty line clears the current comment
        [".", r"\r?\n\r?\n", "CLEAR_COMMENT", None],

        # Ignore whitespace
        [".", r"\s+", "SPACE", None],
        [".", r"\\\n", "SPACE", None],

        # Recognize CLASS() definitions
        ["INITIAL", r"^([A-Z]+)?\s*CLASS\(([A-Z_a-z0-9]+)\s*,\s*([A-Z_a-z0-9]+)\)",
         "PUSH_STATE,CLASS_START", "CLASS"],

        ["CLASS", r"^\s*(FOREIGN|ABSTRACT|PRIVATE)?([0-9A-Z_a-z ]+( |\*))METHOD\(([A-Z_a-z0-9]+),\s*([A-Z_a-z0-9]+),?",
         "PUSH_STATE,METHOD_START", "METHOD"],
        ["METHOD", r"\s*([0-9A-Z a-z_]+\s+\*?\*?)([0-9A-Za-z_]+),?", "METHOD_ARG", None],
        ["METHOD", r"\);", "POP_STATE,METHOD_END", None],

        ["CLASS", r"^\s*(FOREIGN|ABSTRACT)?([0-9A-Z_a-z ]+\s+\*?)\s*([A-Z_a-z0-9]+)\s*;",
         "CLASS_ATTRIBUTE", None],
        ["CLASS", "END_CLASS", "END_CLASS,POP_STATE", None],

        # Recognize struct definitions (With name)
        ["INITIAL", "([A-Z_a-z0-9 ]+)?struct\s+([A-Z_a-z0-9]+)\s+{",
         "PUSH_STATE,STRUCT_START", "STRUCT"],

        # Without name (using typedef)
        ["INITIAL", "typedef\s+struct\s+{",
         "PUSH_STATE,TYPEDEF_STRUCT_START", "STRUCT"],

        ["STRUCT", r"^\s*([0-9A-Z_a-z ]+\s+\*?)\s*([A-Z_a-z0-9]+)(?:\[([A-Z_a-z0-9]+)\])?\s*;",
         "STRUCT_ATTRIBUTE", None],

        ["STRUCT", r"^\s*([0-9A-Z_a-z ]+)\*\s+([A-Z_a-z0-9]+)\s*;",
         "STRUCT_ATTRIBUTE_PTR", None],

        # Struct ended with typedef
        ["STRUCT", "}\s+([0-9A-Za-z_]+);", "POP_STATE,TYPEDEF_STRUCT_END", None],
        ["STRUCT", "}", "POP_STATE,STRUCT_END", None],

        # Handle recursive struct or union definition (At the moment
        # we cant handle them at all)
        ["(RECURSIVE_)?STRUCT", "(struct|union)\s+([_A-Za-z0-9]+)?\s*{", "PUSH_STATE", "RECURSIVE_STRUCT"],
        ["RECURSIVE_STRUCT", "}\s+[0-9A-Za-z]+", "POP_STATE", None],

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

        # Handle proxied directives
        ["INITIAL", r"PXXROXY_CLASS\(([A-Za-z0-9_]+)\)", "PROXY_CLASS", None],

    ]

    def __init__(self, name, verbose=1, base=""):
        self.module = Module(name)
        self.base = base
        super(HeaderParser, self).__init__(verbose=0)

        file_object = io.BytesIO(
            b"// Base object\n"
            b"CLASS(Object, Obj)\n"
            b"END_CLASS\n")
        self.parse_fd(file_object)

    current_comment = ""

    def COMMENT(self, t, m):
        self.current_comment += m.group(1) + "\n"

    def COMMENT_END(self, t, m):
        self.current_comment += m.group(1)

    def CLEAR_COMMENT(self, t, m):
        self.current_comment = ""

    def DEFINE(self, t, m):
        line = m.group(0)
        line = line.split("/*")[0]
        if "\"" in line:
            type = "string"
        else:
            type = "integer"

        name = m.group(1).strip()
        if (len(name) > 3 and name[0] != "_" and name == name.upper() and
            name not in self.module.constants_blacklist):
            self.module.add_constant(name, type)

    current_class = None

    def CLASS_START(self, t, m):
        class_name = m.group(2).strip()
        base_class_name = m.group(3).strip()

        try:
            self.current_class = self.module.classes[base_class_name].clone(class_name)
        except (KeyError, AttributeError):
            log("Base class {0:s} is not defined !!!!".format(base_class_name))
            self.current_class = ClassGenerator(class_name, base_class_name, self.module)

        self.current_class.docstring = self.current_comment
        self.current_class.modifier.add(m.group(1))
        self.module.add_class(self.current_class, Wrapper)
        identifier = "{0:s} *".format(class_name)
        type_dispatcher[identifier] = PointerWrapper

    current_method = None

    def METHOD_START(self, t, m):
        return_type = m.group(2).strip()
        method_name = m.group(5).strip()
        modifier = m.group(1) or ""

        if "PRIVATE" in modifier:
            return

        # Is it a regular method or a constructor?
        self.current_method = Method
        if (return_type == self.current_class.class_name and
            method_name.startswith("Con")):
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
            method_name, [], return_type,
            myclass=self.current_class)
        self.current_method.docstring = self.current_comment
        self.current_method.modifier = modifier

    def METHOD_ARG(self, t, m):
        name = m.group(2).strip()
        type = m.group(1).strip()
        if self.current_method:
            self.current_method.add_arg(type, name)

    def METHOD_END(self, t, m):
        if not self.current_method:
            return

        if isinstance(self.current_method, ConstructorMethod):
            self.current_class.constructor = self.current_method
        else:
            found = False
            for i in range(len(self.current_class.methods)):
                # Try to replace existing methods with this new method
                method = self.current_class.methods[i]
                if method.name == self.current_method.name:
                    self.current_class.methods[i] = self.current_method
                    self.current_method = None
                    return

            # Method does not exist, just add to the end
            self.current_class.methods.append(self.current_method)

        self.current_method = None

    def CLASS_ATTRIBUTE(self, t, m):
        modifier = m.group(1) or ""
        type = m.group(2).strip()
        name = m.group(3).strip()
        self.current_class.add_attribute(name, type, modifier)

    def END_CLASS(self, t, m):
        self.current_class = None

    current_struct = None

    def STRUCT_START(self, t, m):
        self.current_struct = StructGenerator(m.group(2).strip(), self.module)
        self.current_struct.docstring = self.current_comment
        self.current_struct.modifier.add(m.group(1))

    def TYPEDEF_STRUCT_START(self, t, m):
        self.current_struct = StructGenerator(None, self.module)
        self.current_struct.docstring = self.current_comment

    def STRUCT_ATTRIBUTE(self, t, m):
        name = m.group(2).strip()
        type = m.group(1).strip()
        array_size = m.group(3)
        if array_size is not None:
            array_size = array_size.strip()
            self.current_struct.add_attribute(name, type, "", array_size=array_size)
        else:
            self.current_struct.add_attribute(name, type, "")

    def STRUCT_ATTRIBUTE_PTR(self, t, m):
        type = "{0:s} *".format(m.group(1).strip())
        name = m.group(2).strip()
        self.current_struct.add_attribute(name, type, "")

    def STRUCT_END(self, t, m):
        self.module.add_class(self.current_struct, StructWrapper)
        identifier = "{0:s} *".format(self.current_struct.class_name)
        type_dispatcher[identifier] = PointerStructWrapper
        self.current_struct = None

    def TYPEDEF_STRUCT_END(self, t, m):
        self.current_struct.class_name = m.group(1).strip()

        self.STRUCT_END(t, m)

    current_enum = None

    def ENUM_START(self, t, m):
        self.current_enum = Enum(m.group(1).strip(), self.module)

    def TYPEDEF_ENUM_START(self, t, m):
        self.current_enum = Enum(None, self.module)

    def ENUM_VALUE(self, t, m):
        self.current_enum.values.append(m.group(1).strip())

    def ENUM_END(self, t, m):
        self.module.classes[self.current_enum.name] = self.current_enum

        # For now we just treat enums as an integer, and also add
        # them to the constant table. In future it would be nice to
        # have them as a proper Python object so we can override
        # __unicode__, __str__ and __int__.
        for attr in self.current_enum.values:
            self.module.add_constant(attr, "integer")

        # type_dispatcher[self.current_enum.name] = Integer
        type_dispatcher[self.current_enum.name] = EnumType
        self.current_enum = None

    def TYPEDEFED_ENUM_END(self, t, m):
        self.current_enum.name = self.current_enum.class_name = m.group(1)
        self.ENUM_END(t, m)

    def BIND_STRUCT(self, t, m):
        self.module.active_structs.add(m.group(1))
        self.module.active_structs.add("{0:s} *".format(m.group(1)))

    def SIMPLE_TYPEDEF(self, t, m):
        # We basically add a new type as a copy of the old
        # type
        old, new = m.group(1).strip(), m.group(2).strip()
        if old in type_dispatcher:
            type_dispatcher[new] = type_dispatcher[old]

    def PROXY_CLASS(self, t, m):
        base_class_name = m.group(1).strip()
        class_name = "Proxied{0:s}".format(base_class_name)
        try:
            proxied_class = self.module.classes[base_class_name]
        except KeyError:
            raise RuntimeError((
                "Need to create a proxy for {0:s} but it has not been "
                "defined (yet). You must place the PROXIED_CLASS() "
                "instruction after the class definition").format(
                    base_class_name))
        current_class = ProxyClassGenerator(class_name,
                                            base_class_name, self.module)
        # self.current_class.constructor.args += proxied_class.constructor.args
        current_class.docstring = self.current_comment

        # Create proxies for all these methods
        for method in proxied_class.methods:
            if method.name[0] != "_":
                current_class.methods.append(ProxiedMethod(method, current_class))

        self.module.add_class(current_class, Wrapper)

    def parse_filenames(self, filenames):
        for f in filenames:
            self._parse(f)

        # Second pass
        for f in filenames:
            self._parse(f)

    def _parse(self, filename):
        file_object = open(filename, "rb")
        self.parse_fd(file_object)
        file_object.close()

        if filename not in self.module.files:
            if filename.startswith(self.base):
                filename = filename[len(self.base):]

            self.module.headers += "#include \"{0:s}\"\n".format(filename)
            self.module.files.append(filename)

    def write(self, out):
        try:
            self.module.write(out)
        except:
            # pdb.post_mortem()
            raise

    def write_headers(self):
        pass
        # pdb.set_trace()


if __name__ == "__main__":
    p = HeaderParser("pytsk3", verbose=1)
    for arg in sys.argv[1:]:
        p.parse_fd(open(arg, "rb"))

    log("second parse")
    for arg in sys.argv[1:]:
        p.parse_fd(open(arg, "rb"))

    p.write(sys.stdout)
    p.write_headers()

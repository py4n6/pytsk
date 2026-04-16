diff --git a/tsk/base/crc.h b/tsk/base/crc.h
index f9f4617c3..f73426c36 100644
--- a/tsk/base/crc.h
+++ b/tsk/base/crc.h
@@ -91,7 +91,7 @@ Status  : Copyright (C) Ross Williams, 1993. However, permission is
 #ifndef DONE_STYLE
 
 typedef unsigned long   ulong;
-typedef unsigned        bool;
+typedef unsigned        crc_bool;
 typedef unsigned char * p_ubyte_;
 
 #ifndef TRUE
@@ -120,8 +120,8 @@ typedef struct
    int   cm_width;   /* Parameter: Width in bits [8,32].       */
    ulong cm_poly;    /* Parameter: The algorithm's polynomial. */
    ulong cm_init;    /* Parameter: Initial register value.     */
-   bool  cm_refin;   /* Parameter: Reflect input bytes?        */
-   bool  cm_refot;   /* Parameter: Reflect output CRC?         */
+   crc_bool  cm_refin;   /* Parameter: Reflect input bytes?        */
+   crc_bool  cm_refot;   /* Parameter: Reflect output CRC?         */
    ulong cm_xorot;   /* Parameter: XOR this to output CRC.     */
 
    ulong cm_reg;     /* Context: Context during execution.     */

diff --git a/tsk/fs/fatfs_utils.c b/tsk/fs/fatfs_utils.c
index 9495ac923..440b0dff8 100755
--- a/tsk/fs/fatfs_utils.c
+++ b/tsk/fs/fatfs_utils.c
@@ -179,8 +179,11 @@ fatfs_dos_2_unix_time(uint16_t date, uint16_t time, uint8_t timetens)
      * it out */
     tm1.tm_isdst = -1;
 
-    ret = mktime(&tm1);
-
+#if defined( _MSC_VER )
+    ret = _mkgmtime(&tm1);
+#else
+    ret = timegm(&tm1);
+#endif
     if (ret < 0) {
         if (tsk_verbose)
             tsk_fprintf(stderr,

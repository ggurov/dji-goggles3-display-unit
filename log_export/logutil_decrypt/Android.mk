LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := logutil_decrypt
LOCAL_SRC_FILES := logutil_decrypt.c
LOCAL_LDLIBS := -ldl
include $(BUILD_EXECUTABLE)

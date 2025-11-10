import os
import subprocess
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# --- Helper function to find OpenCV ---
# This tries to find OpenCV using pkg-config, which is common on Linux
def get_opencv_flags():
    try:
        # Check if pkg-config is available
        subprocess.run(['pkg-config', '--version'], check=True, capture_output=True)
        
        # Get C flags (include directories)
        cflags = subprocess.check_output(
            ['pkg-config', '--cflags', 'opencv4']
        ).decode('utf-8').strip().split()
        
        # Get linker flags (library directories and libraries)
        libs = subprocess.check_output(
            ['pkg-config', '--libs', 'opencv4']
        ).decode('utf-8').strip().split()
            
        print(f"Found OpenCV flags:\nIncludes: {cflags}\nLibs: {libs}")
        return cflags, libs

    except Exception as e:
        print(f"Warning: Could not find OpenCV using pkg-config: {e}")
        print("Falling back to manual paths. You may need to edit this setup.py.")
        # FALLBACK: Manually specify paths if pkg-config fails
        # --- EDIT THESE IF NEEDED ---
        OPENCV_INCLUDE_DIR = '/usr/include/opencv4'
        OPENCV_LIB_DIR = '/usr/lib/x86_64-linux-gnu'
        # --- -------------------- ---
        
        # Manually list common OpenCV libraries
        manual_libs = [
            '-lopencv_core', 
            '-lopencv_imgcodecs', 
            '-lopencv_imgproc', 
            '-lopencv_videoio'
        ]
        
        return [f'-I{OPENCV_INCLUDE_DIR}'], [f'-L{OPENCV_LIB_DIR}'] + manual_libs

# --- pybind11 setup ---
class get_pybind_include(object):
    """Helper class to fetch pybind11 include path"""
    def __str__(self):
        import pybind11
        return pybind11.get_include()

opencv_cflags, opencv_libs = get_opencv_flags()

ext_modules = [
    Extension(
        'video_maker_cpp', # The name of the module
        ['video_maker_cpp.cpp'], # Source file
        include_dirs=[
            get_pybind_include(),
            # Add OpenCV include dirs
            *[flag[2:] for flag in opencv_cflags if flag.startswith('-I')]
        ],
        language='c++',
        extra_compile_args=['-std=c++17', '-O3'] + [flag for flag in opencv_cflags if not flag.startswith('-I')],
        extra_link_args=opencv_libs
    ),
]

setup(
    name='video_maker_cpp',
    version='0.1.0',
    author='Shinken',
    author_email='konrad.suchodolski50@gmail.com',
    description='C++ accelerator for video making',
    ext_modules=ext_modules,
    install_requires=['pybind11>=2.6'],
    cmdclass={'build_ext': build_ext},
    zip_safe=False,
)
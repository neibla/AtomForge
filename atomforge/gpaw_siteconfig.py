"""CUDA build configuration for the Modal GPAW worker."""

gpu = True
gpu_target = "cuda"
gpu_compiler = "nvcc"
gpu_compile_args = [
    "-O3",
    "-gencode",
    "arch=compute_80,code=sm_80",
    "-gencode",
    "arch=compute_90,code=sm_90",
]
libraries = [
    "openblas",
    "fftw3",
    "xc",
    "scalapack-openmpi",
    "cudart",
    "cublas",
]
library_dirs = [
    "/usr/local/cuda/lib64",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu/openblas-pthread",
    "/usr/lib/x86_64-linux-gnu/openmpi/lib",
]
runtime_library_dirs = library_dirs
include_dirs = ["/usr/local/cuda/include"]
undef_macros = ["GPAW_GPU_AWARE_MPI"]

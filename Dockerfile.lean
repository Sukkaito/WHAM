FROM python:3.9-slim

# Install git and wget
RUN apt-get update && apt-get install -y \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY . /code

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV CUDA_VISIBLE_DEVICES=""
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV VECLIB_MAXIMUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV KMP_INIT_AT_FORK=FALSE
ENV MPLBACKEND=Agg
ENV PYTHONFAULTHANDLER=1

FROM python:3.13-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        autoconf \
        automake \
        cmake \
        curl \
        git \
        libtool \
        pkg-config \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir \
        "VapourSynth==79" \
        "hatchling>=1.30" \
        "meson>=0.49" \
        ninja \
        packaging

WORKDIR /workspace

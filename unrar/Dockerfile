FROM ubuntu:26.04

# Set environment variables for non-interactive installations
ENV DEBIAN_FRONTEND=noninteractive

# Update package list and install necessary dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        unrar locales \
    && locale-gen ja_JP.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=ja_JP.UTF-8 \
    LANGUAGE=ja_JP:ja \
    LC_ALL=ja_JP.UTF-8

WORKDIR /workspace

ENTRYPOINT [ "unrar", "x" ]

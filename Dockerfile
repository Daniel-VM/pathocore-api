FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid
ENV APP_REPO_PATH=/srv/pathocore-api
ENV APP_INSTALL_PATH=/opt/pathocore-api
ENV APP_PORT=8000
ENV APP_READY_FILE=/opt/pathocore-api/.container_install_ready

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    lsb-release \
    python3 \
    python3-pip \
    python3-venv \
    rsync \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/pathocore-api

COPY . /srv/pathocore-api

RUN chmod +x /srv/pathocore-api/install.sh \
    && chmod +x /srv/pathocore-api/container_install.sh \
    && chmod +x /srv/pathocore-api/scripts/container_start.sh \
    && chmod +x /srv/pathocore-api/scripts/databrowser_cache_scheduler.sh

ARG GIT_REVISION=develop
ARG INSTALL_CONF=conf/docker_test_settings.txt

# Prepare system/python dependencies in the image. App installation and DB
# migration are executed later by container_install.sh once containers are up.
RUN bash install.sh --install dep --git_revision "$GIT_REVISION" --conf "$INSTALL_CONF" --docker

EXPOSE 8000

CMD ["/srv/pathocore-api/scripts/container_start.sh"]

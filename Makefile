.PHONY: build-base push-base test clean

BASE ?= talebook/talebook-base
BASE_VER ?= slim-v8.5.0
BUILD_COUNTRY ?=
BASE_PLATFORMS ?= linux/arm64

build-base:
	docker build -f Dockerfile --build-arg BUILD_COUNTRY=$(BUILD_COUNTRY) -t $(BASE):$(BASE_VER) -t $(BASE):latest .

test: build-base
	docker run --rm -v "$$PWD":"$$PWD" -w "$$PWD" --entrypoint /bin/sh $(BASE):$(BASE_VER) packaging/smoke-test.sh

push-base:
	docker buildx build -f Dockerfile --build-arg BUILD_COUNTRY=$(BUILD_COUNTRY) --platform $(BASE_PLATFORMS) -t $(BASE):$(BASE_VER) -t $(BASE):latest --push .

clean:
	rm -rf .build/calibre-runtime

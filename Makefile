IMAGE_NAME=hive-agent
TAG=dev

install:
	docker build -t $(IMAGE_NAME):$(TAG) -f Dockerfile.dev .

run:
	docker run --rm $(IMAGE_NAME):$(TAG)

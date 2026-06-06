.PHONY: build run test clean

build:
	go build -o bin/{{PROJECT_NAME}} .

run:
	go run .

test:
	go test -v ./...

test-coverage:
	go test -coverprofile=coverage.out ./...
	go tool cover -html=coverage.out -o coverage.html

clean:
	rm -rf bin/ coverage.out coverage.html

lint:
	golangci-lint run

fmt:
	go fmt ./...

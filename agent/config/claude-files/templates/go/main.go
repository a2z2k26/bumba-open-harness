package main

import (
	"fmt"
	"os"

	"github.com/joho/godotenv"
)

func main() {
	// Load .env file
	godotenv.Load()

	fmt.Println("Hello from {{PROJECT_NAME}}!")
	env := os.Getenv("ENV")
	if env == "" {
		env = "development"
	}
	fmt.Printf("Environment: %s\n", env)
}

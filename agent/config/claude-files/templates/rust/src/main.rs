//! {{PROJECT_NAME}} - Generated with Bumba Sandbox Orchestrator

use std::env;

fn main() {
    // Load .env file
    dotenv::dotenv().ok();

    println!("Hello from {{PROJECT_NAME}}!");

    let environment = env::var("ENV").unwrap_or_else(|_| "development".to_string());
    println!("Environment: {}", environment);
}

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert!(true);
    }
}

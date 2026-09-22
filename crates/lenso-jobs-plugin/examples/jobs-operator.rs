use std::{env, error::Error};

use lenso_jobs_plugin::JobsOperator;

const DATABASE_URL_ENVIRONMENT: &str = "LENSO_JOBS_DATABASE_URL";

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = env::args().skip(1);
    let command = arguments
        .next()
        .ok_or("expected setup, upgrade, or check")?;
    let schema = arguments.next().ok_or("expected one schema name")?;
    if arguments.next().is_some() {
        return Err("expected exactly one schema name".into());
    }
    let database_url = env::var(DATABASE_URL_ENVIRONMENT)
        .map_err(|_| format!("{DATABASE_URL_ENVIRONMENT} is required"))?;

    match command.as_str() {
        "setup" => {
            JobsOperator::setup(&database_url, &schema).await?;
            println!("Jobs schema `{schema}` is ready");
        }
        "upgrade" => {
            JobsOperator::upgrade(&database_url, &schema).await?;
            println!("Jobs schema `{schema}` is upgraded");
        }
        "check" => {
            JobsOperator::connect(&database_url, &schema).await?;
            println!("Jobs schema `{schema}` matches this Plugin version");
        }
        _ => return Err("expected setup, upgrade, or check".into()),
    }
    Ok(())
}

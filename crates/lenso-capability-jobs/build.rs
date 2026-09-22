fn main() {
    println!("cargo:rerun-if-changed=capability.json");
    println!("cargo:rerun-if-changed=schemas");
    println!("cargo:rerun-if-changed=src/generated.rs");
    lenso_contract_codegen::check_projection(
        std::path::Path::new("capability.json"),
        lenso_contract_codegen::ProjectionLanguage::RustRuntime,
        std::path::Path::new("src/generated.rs"),
    )
    .expect("stale generated Jobs Capability projection");
}

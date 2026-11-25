use super::*;

#[test]
fn recursive_forbid_keys_and_bola_pair_validation() {
    let nested = parse_json(r#"{"status":200,"details":{"token":"leak"}}"#).unwrap();
    assert!(has_key_recursive(&nested, "token", true));
    let prose = parse_json(r#"{"status":200,"message":"token=ok"}"#).unwrap();
    assert!(!has_key_recursive(&prose, "token", true));
    let same_owner = parse_json(r#"{"actor_owner":"t1","resource_owner":"t1"}"#).unwrap();
    assert!(check_bola_variant_pair("c.deny", &same_owner).is_err());
    let cross_owner = parse_json(r#"{"actor_owner":"t1","resource_owner":"t2"}"#).unwrap();
    assert_eq!(check_bola_variant_pair("c.deny", &cross_owner).unwrap(), true);
}

#[test]
fn canonical_rust_test_id_and_list_terse_homonym_parity() {
    // Top-level test
    let (_, t_top) = parse_list_terse_output("drift_contracts", "top: test\n");
    assert_eq!(t_top, vec![canonical_rust_test_id("drift_contracts", "drift_contracts", "top")]);
    // Submodule sharing crate name: mod drift_contracts { fn homonym() {} }
    let (_, t_hom) = parse_list_terse_output("drift_contracts", "drift_contracts::homonym: test\n");
    assert_eq!(
        t_hom,
        vec![canonical_rust_test_id(
            "drift_contracts",
            "drift_contracts::drift_contracts",
            "homonym"
        )]
    );
    // Nested submodule under homonym module: mod drift_contracts { mod sub { fn nested() {} } }
    let (_, t_nest) =
        parse_list_terse_output("drift_contracts", "drift_contracts::sub::nested: test\n");
    assert_eq!(
        t_nest,
        vec![canonical_rust_test_id(
            "drift_contracts",
            "drift_contracts::drift_contracts::sub",
            "nested"
        )]
    );
}

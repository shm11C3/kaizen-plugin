pub fn within_limit(distance: u64, limit: u64) -> bool {
    distance <= limit
}

#[cfg(test)]
mod tests {
    use super::within_limit;

    #[test]
    fn boundary() {
        assert!(within_limit(10, 10));
        assert!(!within_limit(11, 10));
    }
}

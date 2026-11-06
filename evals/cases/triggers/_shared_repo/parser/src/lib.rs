pub fn first_field(line: &str) -> &str {
    let parts: Vec<&str> = line.split(',').collect();
    parts[0].trim().split_at(1).1
}

def write_users(users, path):
    with open(path, "w") as handle:
        handle.write("id,name\n")
        for user in users:
            handle.write(f"{user.id},{user.name}\n")

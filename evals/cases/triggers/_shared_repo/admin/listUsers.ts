export async function listUsers(fetcher: (url: string) => Promise<any>) {
  return fetcher("/api/users");
}

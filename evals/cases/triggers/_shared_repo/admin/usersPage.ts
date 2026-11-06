import { listUsers } from "./listUsers";

export async function renderUsers(fetcher: (url: string) => Promise<any>) {
  const users = await listUsers(fetcher);
  return users.map((user: any) => user.name).join("\n");
}

export * from "./lib/api";
export { UserList as default } from "./components/UserList";
export { formatName } from "./utils/format";

export async function loadLazy() {
  const module = await import("./components/UserCard");
  return module.UserCard;
}

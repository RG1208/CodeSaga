import UserList from "@/index";
import { createUser, getUsers } from "@/index";
import * as format from "./utils/format";

export default function App() {
  const onCreate = async () => {
    await createUser("ada");
    await getUsers();
  };
  return <UserList title={format.formatName("Team")} />;
}

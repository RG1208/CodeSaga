/** A registered user. */
export interface User {
  id: string;
  name: string;
}

export type UserId = User["id"];

export enum Role {
  Admin = "admin",
  Member = "member",
}

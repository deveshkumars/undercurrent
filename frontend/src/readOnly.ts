import { createContext, useContext } from "react";

// True for public-demo visitors without the access code: the UI hides actions that write or spend credits
// (the API refuses them anyway).
export const ReadOnlyContext = createContext(false);

export function useReadOnly(): boolean {
  return useContext(ReadOnlyContext);
}

import { SWRConfig } from "swr";
import AppRouter from "./router";

export default function App() {
  return (
    <SWRConfig value={{ revalidateOnFocus: false, shouldRetryOnError: false }}>
      <AppRouter />
    </SWRConfig>
  );
}

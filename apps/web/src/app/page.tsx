import { App } from "@/components/App";
import { ClientOnly } from "@/components/ClientOnly";

export default function Home() {
  return (
    <ClientOnly fallback={<div className="p-6 text-sm text-zinc-500">Loading BinderScan…</div>}>
      <App />
    </ClientOnly>
  );
}

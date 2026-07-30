import type { Metadata } from "next";
import { NewDraftForm } from "@/components/mock-draft/new-draft-form";
import { SetupRequired } from "@/components/mock-draft/setup-required";

export const metadata: Metadata = { title: "Create Mock Draft" };

export default function NewMockDraftPage() {
  const configured = Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );
  return configured ? <NewDraftForm /> : <SetupRequired />;
}


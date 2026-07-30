import type { Metadata } from "next";
import { MockDraftResults } from "@/components/mock-draft/mock-draft-results";

export const metadata: Metadata = { title: "Mock Draft Results" };

export default async function MockDraftResultsPage({
  params,
}: {
  params: Promise<{ draftId: string }>;
}) {
  const { draftId } = await params;
  return <MockDraftResults draftKey={draftId} />;
}


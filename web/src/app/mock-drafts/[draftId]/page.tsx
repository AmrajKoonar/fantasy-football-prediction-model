import type { Metadata } from "next";
import { MockDraftRoom } from "@/components/mock-draft/mock-draft-room";

export const metadata: Metadata = { title: "Mock Draft Room" };

export default async function MockDraftRoomPage({
  params,
}: {
  params: Promise<{ draftId: string }>;
}) {
  const { draftId } = await params;
  return <MockDraftRoom draftKey={draftId} />;
}


import type { Metadata } from "next";
import { Suspense } from "react";

import { NewsroomView } from "@/components/newsroom/newsroom-view";

// Judul tab statis di server (tanpa layout bersarang bermetadata, yang akan mereset template judul root).
export const metadata: Metadata = { title: "Newsroom" };

// `useSearchParams` di NewsroomView mewajibkan batas Suspense saat build.
export default function NewsroomPage() {
  return (
    <Suspense>
      <NewsroomView />
    </Suspense>
  );
}

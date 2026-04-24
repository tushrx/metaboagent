import { EvidenceRail } from "@/components/evidence-rail";
import { Header } from "@/components/header";
import { MainPane } from "@/components/main-pane";

export default function Home() {
  return (
    <>
      <Header />
      <div className="flex h-[calc(100vh-56px)]">
        <MainPane />
        <EvidenceRail />
      </div>
    </>
  );
}

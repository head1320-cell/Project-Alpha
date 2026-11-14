import DbStatusPanel from "@/widgets/admin/DbStatusPanel";

export const metadata = {
  title: "데이터 상태",
  description: "데이터 원천 연결·적재 현황과 연구 등급",
};

export default function DataInfraPage() {
  return <DbStatusPanel />;
}

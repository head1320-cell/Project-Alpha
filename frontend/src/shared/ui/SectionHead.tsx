// 인덱스 달린 구분선 섹션 헤드 — 백테스터 .tbt-divider-label 모티프를 일반화.
// 백테스터 자체 클래스는 건드리지 않음(무변경). 프레젠테이션 전용.
export default function SectionHead({ label, index }: { label: string; index?: string }) {
  return (
    <div className="tpage-section-head">
      <span className="sh-label">{label}</span>
      {index != null && <span className="sh-index">{index}</span>}
    </div>
  );
}

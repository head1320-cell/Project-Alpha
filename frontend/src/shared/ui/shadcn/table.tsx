// shadcn/ui Table — 손으로 작성한 벤더링본. Radix 의존 없음.
//
// ★상류의 p-4 를 쓰지 않는다★ card.tsx 헤더와 같은 이유. 상류는 셀에 `p-4`(16px)와
// `h-12`(48px) 행을 준다. 지표 표에서 그 값이면 한 화면에 8행이 안 들어간다.
// 기본을 px-2.5 py-1.5 로 정한다 — 넓히고 싶으면 소비처에서 className 으로 늘린다.
//
// ★숫자 열은 소비처가 `.num text-right` 를 붙인다★ 여기서 강제하지 않는 이유:
// 이 표는 숫자 전용이 아니고, `.num`(globals.css:358, tabular-nums)이 이 저장소의
// 규약이라 컴포넌트가 아니라 열 단위로 붙는 것이 맞다(AAS 안에서만 296곳이 그렇게 쓴다).
import * as React from "react";
import { cn } from "@/shared/lib/cn";

/** 가로 스크롤 래퍼 포함 — 표가 좁은 폭에서 페이지를 밀지 않게 한다. */
const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <div className="relative w-full overflow-x-auto">
      <table
        ref={ref}
        className={cn("w-full caption-bottom border-collapse text-[12px]", className)}
        {...props}
      />
    </div>
  ),
);
Table.displayName = "Table";

const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead ref={ref} className={cn("[&_tr]:border-b [&_tr]:border-[var(--border)]", className)} {...props} />
  ),
);
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
  ),
);
TableBody.displayName = "TableBody";

const TableFooter = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tfoot
      ref={ref}
      className={cn("border-t border-[var(--border)] font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  ),
);
TableFooter.displayName = "TableFooter";

const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        "border-b border-[var(--border)] transition-colors hover:bg-[var(--muted)]",
        className,
      )}
      {...props}
    />
  ),
);
TableRow.displayName = "TableRow";

/**
 * `scope` 를 필수로 받는다 — 상류에는 없는 유일한 차이이고, 이유가 있다.
 * scope 없는 <th> 는 스크린리더가 어느 축의 머리글인지 못 정해서, 셀을 읽을 때
 * "무엇의 값인지"를 말해 주지 못한다. 숫자만 있는 비교표에서는 그게 표를 못 쓰게 만든다.
 * 타입으로 강제하면 잊을 수가 없다.
 */
export interface TableHeadProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  scope: "col" | "row" | "colgroup" | "rowgroup";
}
const TableHead = React.forwardRef<HTMLTableCellElement, TableHeadProps>(
  ({ className, ...props }, ref) => (
    <th
      ref={ref}
      className={cn(
        "px-2.5 py-1.5 text-left align-middle font-semibold text-[11px]",
        "uppercase tracking-wide text-[var(--muted-foreground)]",
        className,
      )}
      {...props}
    />
  ),
);
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <td ref={ref} className={cn("px-2.5 py-1.5 align-middle", className)} {...props} />
  ),
);
TableCell.displayName = "TableCell";

const TableCaption = React.forwardRef<HTMLTableCaptionElement, React.HTMLAttributes<HTMLTableCaptionElement>>(
  ({ className, ...props }, ref) => (
    <caption ref={ref} className={cn("mt-2 text-[11px] text-[var(--muted-foreground)]", className)} {...props} />
  ),
);
TableCaption.displayName = "TableCaption";

export {
  Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption,
};

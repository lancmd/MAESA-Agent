import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'MAESA Skill｜矿区生态分析应用技能',
  description: '面向全国矿区的本地生态分析应用技能：LULC、PLUS、InVEST 与科研制图。',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

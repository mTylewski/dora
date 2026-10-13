// Page texts from PDFs, entirely in the browser: the text layer via pdf.js, scanned pages via local OCR
// (tesseract.js with the Polish model served from our own domain). Nothing is uploaded.
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { OEM, createWorker, type Worker as OcrWorker } from "tesseract.js";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/** A page with fewer non-whitespace characters than this is treated as a scan (same as the MVP). */
const MIN_TEXT_CHARS = 40;
const OCR_SCALE = 2.5; // about 180-200 DPI for A4

export interface PdfText { pages: string[]; ocrPages: number[] }
export type PageProgress = (page: number, pages: number, ocr: boolean) => void;

let ocrWorker: Promise<OcrWorker> | null = null;

function getOcr(): Promise<OcrWorker> {
  ocrWorker ??= createWorker("pol", OEM.LSTM_ONLY, {
    workerPath: "/ocr/worker.min.js",
    corePath: "/ocr/core",
    langPath: "/ocr/lang",
    gzip: true,
    workerBlobURL: false,
  });
  return ocrWorker;
}

async function ocrPage(page: pdfjs.PDFPageProxy): Promise<string> {
  const viewport = page.getViewport({ scale: OCR_SCALE });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const context = canvas.getContext("2d")!;
  await page.render({ canvas, canvasContext: context, viewport }).promise;
  const worker = await getOcr();
  const { data } = await worker.recognize(canvas);
  canvas.width = canvas.height = 0; // free memory
  return data.text;
}

export async function readPdfText(data: ArrayBuffer, onPage?: PageProgress): Promise<PdfText> {
  const task = pdfjs.getDocument({ data: new Uint8Array(data.slice(0)) });
  const doc = await task.promise;
  const pages: string[] = [];
  const ocrPages: number[] = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const content = await page.getTextContent();
    let text = "";
    for (const item of content.items) {
      if (!("str" in item)) continue;
      text += item.str + (item.hasEOL ? "\n" : " ");
    }
    const scanned = text.replace(/\s/g, "").length < MIN_TEXT_CHARS;
    onPage?.(i, doc.numPages, scanned);
    if (scanned) {
      text = await ocrPage(page);
      ocrPages.push(i);
    }
    pages.push(text);
  }
  await task.destroy();
  return { pages, ocrPages };
}

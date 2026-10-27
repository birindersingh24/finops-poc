import { Injectable } from '@nestjs/common';
import csvParser from 'csv-parser';
import fs from 'fs';
import { pipeline, FeatureExtractionPipeline } from '@huggingface/transformers';

@Injectable()
export class CsvChunkService {
  private extractor: FeatureExtractionPipeline;

  // async onModuleInit() {
  //   this.extractor = await pipeline(
  //     'feature-extraction',
  //     'Xenova/all-MiniLM-L6-v2',
  //   );
  // }
  createChunks(): Promise<string[]> {
    try {
      return new Promise((resolve, reject) => {
        const results: string[] = [];
        fs.createReadStream('mocks/focus_mock_costandusage.csv')
          .on('error', reject)
          .pipe(csvParser())
          .on('error', reject)
          .on('data', (row) => {
            let rowList: string = '';
            for (const key in row) {
              rowList = rowList + `${key}: ${row[key]},`;
            }
            results.push(rowList);
          })
          .on('end', () => resolve(results));
      });
    } catch (error) {
      throw new Error(`Error occurred while creating CSV chunks: ${error}`);
    }
  }

  async embeddingChunks(chunks: string[], batchSize = 32): Promise<number[][]> {
    try {
      this.extractor = await pipeline(
        'feature-extraction',
        'Xenova/all-MiniLM-L6-v2',
      );
      const vectors: number[][] = [];
      for (let i = 0; i < chunks.length; i += batchSize) {

        const batch = chunks.slice(i, i + batchSize);
        const output = await this.extractor(batch, {
          pooling: 'mean',
          normalize: true,
        });
        vectors.push(...(output.tolist() as number[][]));
      }
      return vectors;
    } catch (error) {
      throw new Error(`Error occurred while creating CSV chunks: ${error}`);
    }
  }
}

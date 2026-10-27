import { Injectable } from '@nestjs/common';
import csvParser from 'csv-parser';
import fs from 'fs';
import { pipeline, FeatureExtractionPipeline } from '@huggingface/transformers';

@Injectable()
export class CsvChunkService {
  private extractor: FeatureExtractionPipeline;

  async onModuleInit() {
    this.extractor = await pipeline(
      'feature-extraction',
      'Xenova/all-MiniLM-L6-v2',
    );
  }
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

            rowList =
              `${row.ProviderName} ${row.ServiceName} in ${row.RegionName}: ${row.ChargeDescription}. ` +
              `Cost ${row.EffectiveCost} ${row.BillingCurrency} on ${row.ChargePeriodStart.slice(0, 10)}.`;

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

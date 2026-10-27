import { Module } from '@nestjs/common';
import { CsvChunkController } from './csv-chunks.controller.js';
import { CsvChunkService } from './csv-chunks.service.js';

@Module({
  controllers: [CsvChunkController],
  providers: [CsvChunkService],
})
export class CsvChunksModule {}

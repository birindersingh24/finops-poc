import { Controller, Get } from '@nestjs/common';
import { CsvChunkService } from './csv-chunks.service.js';

@Controller('csv-chunks')
export class CsvChunkController {
  constructor(private readonly costsService: CsvChunkService) {}

  @Get()
  async chunkingAndEmbedding() {
    const chunks = await this.costsService.createChunks();
    return await this.costsService.embeddingChunks(chunks)
  }
}

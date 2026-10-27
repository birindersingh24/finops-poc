import { Test, TestingModule } from '@nestjs/testing';
import { CsvChunkService } from './csv-chunks.service.js';

describe('CostsService', () => {
  let service: CsvChunkService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [CsvChunkService],
    }).compile();

    service = module.get<CsvChunkService>(CsvChunkService);
  });

  it('should return all costs', () => {
    expect(service.createChunks()).toEqual([
      { id: 1, service: 'EC2', amount: 1200 },
    ]);
  });
});
